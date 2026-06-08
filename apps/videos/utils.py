import logging
import os
import shutil
import subprocess
import urllib.request
from typing import Optional

from django.db.models import Q
from .models import ChatRoom

logger = logging.getLogger(__name__)

# ─── Audio constants ──────────────────────────────────────────────────────────
_AUDIO_BITRATE  = "192k"
_AUDIO_RATE     = "44100"
_AUDIO_CHANNELS = "2"
_FFMPEG_TIMEOUT = 300   # 5 min hard cap for audio render
_VOLUME_ZERO    = 0.005 # treat anything ≤ this as "muted"


def _probe_has_audio(video_path: str) -> bool:
    """Return True if the video file contains at least one audio stream."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True, text=True, timeout=120,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _run_ffmpeg_mix(cmd: list[str], label: str) -> bool:
    """Run an FFmpeg command; log stderr on failure. Returns True on success."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("[audio_mix] FFmpeg timed out (%s)", label)
        return False

    if result.returncode != 0:
        logger.error(
            "[audio_mix] FFmpeg failed (rc=%d, %s):\n%s",
            result.returncode, label, result.stderr[-3000:],
        )
        return False
    return True


def mix_audio_into_video(
    video_path: str,
    audio_url: str,
    volume_original: float,
    volume_music: float,
    audio_trim_start: float = 0.0,
) -> Optional[str]:
    """
    Production-quality audio mixer — TikTok style.

    Downloads *audio_url*, mixes it into *video_path* with independent
    volume controls and replaces the file in-place.

    Behaviour matrix
    ─────────────────────────────────────────────────────────────────────
    video audio │ vol_original │ vol_music │ result
    ────────────┼──────────────┼───────────┼──────────────────────────────
    present     │   > 0        │   > 0     │ mix both streams (amix)
    present     │   ≈ 0        │   > 0     │ drop original, add music only
    present     │   > 0        │   ≈ 0     │ keep original at vol_original
    silent      │   any        │   > 0     │ add music only
    silent      │   any        │   ≈ 0     │ no-op (nothing to do)
    ─────────────────────────────────────────────────────────────────────

    All output is:
      • Stereo 44 100 Hz AAC 192 kbps
      • -movflags +faststart  → moov atom at start (critical for web/mobile)
      • Music loops to match video duration (TikTok behavior)
      • amix normalize=0      → no automatic volume ducking
    """
    if not os.path.isfile(video_path):
        logger.error("[audio_mix] Video not found: %s", video_path)
        return None

    # Clamp volumes to [0, 1]
    volume_original = max(0.0, min(1.0, float(volume_original)))
    volume_music    = max(0.0, min(1.0, float(volume_music)))

    mute_original = volume_original <= _VOLUME_ZERO
    mute_music    = volume_music    <= _VOLUME_ZERO
    audio_trim_start = max(0.0, float(audio_trim_start))

    # ── 1. Download music track ───────────────────────────────────────────────
    if not mute_music:
        audio_ext  = os.path.splitext(audio_url.split("?")[0])[-1] or ".mp3"
        # Store tmp file next to the video to stay on the same filesystem
        audio_path = video_path + ".tmp_track" + audio_ext
        try:
            urllib.request.urlretrieve(audio_url, audio_path)
        except Exception as exc:
            logger.error("[audio_mix] Could not download audio %s — %s", audio_url, exc)
            return None
    else:
        audio_path = None

    # ── 2. Detect video audio stream ─────────────────────────────────────────
    has_video_audio = _probe_has_audio(video_path)

    # ── 3. Decide strategy ───────────────────────────────────────────────────
    # Output is placed next to the source (same filesystem → no cross-device copy)
    output_path = video_path + ".tmp_mix.mp4"

    # Common output flags (applied to every branch)
    _out_flags = [
        "-c:v", "copy",          # never re-encode video — preserves quality & speed
        "-c:a", "aac",
        "-b:a", _AUDIO_BITRATE,
        "-ar", _AUDIO_RATE,
        "-ac", _AUDIO_CHANNELS,
        "-movflags", "+faststart",   # moov atom first → instant web/mobile play
        "-shortest",                 # trim to shortest stream (video duration)
        output_path,
    ]

    try:
        if mute_music and not has_video_audio:
            # Nothing to do — video is already silent and music is muted
            logger.info("[audio_mix] No-op: video is silent and music is muted")
            return video_path

        elif mute_music:
            # ── Only original audio at adjusted volume ────────────────────
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-filter_complex", f"[0:a]volume={volume_original:.4f}[out]",
                "-map", "0:v:0",
                "-map", "[out]",
                *_out_flags,
            ]
            success = _run_ffmpeg_mix(cmd, "original-only")

        elif not has_video_audio or mute_original:
            # ── Music only (looped to video length) ───────────────────────
            # atrim skips to the selected block, asetpts resets timestamps,
            # then aloop loops from that point to fill the video duration.
            if audio_trim_start > 0:
                fc = (
                    f"[1:a]atrim=start={audio_trim_start:.4f},asetpts=PTS-STARTPTS,"
                    f"aloop=loop=-1:size=2147483647,volume={volume_music:.4f}[out]"
                )
            else:
                fc = f"[1:a]volume={volume_music:.4f}[out]"
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-stream_loop", "-1", "-i", audio_path,
                "-filter_complex", fc,
                "-map", "0:v:0",
                "-map", "[out]",
                *_out_flags,
            ]
            success = _run_ffmpeg_mix(cmd, "music-only")

        else:
            # ── Full mix: original + looped music ────────────────────────
            if audio_trim_start > 0:
                filter_complex = (
                    f"[0:a]volume={volume_original:.4f}[va];"
                    f"[1:a]atrim=start={audio_trim_start:.4f},asetpts=PTS-STARTPTS,"
                    f"aloop=loop=-1:size=2147483647,volume={volume_music:.4f}[ma];"
                    "[va][ma]amix=inputs=2:duration=first:normalize=0[out]"
                )
            else:
                filter_complex = (
                    f"[0:a]volume={volume_original:.4f}[va];"
                    f"[1:a]volume={volume_music:.4f}[ma];"
                    "[va][ma]amix=inputs=2:duration=first:normalize=0[out]"
                )
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-stream_loop", "-1", "-i", audio_path,
                "-filter_complex", filter_complex,
                "-map", "0:v:0",
                "-map", "[out]",
                *_out_flags,
            ]
            success = _run_ffmpeg_mix(cmd, "full-mix")

        if not success:
            return None

        # ── 4. Atomic replace (same filesystem → rename is instantaneous) ──
        os.replace(output_path, video_path)
        logger.info(
            "[audio_mix] Done — vol_orig=%.0f%% vol_music=%.0f%% has_orig_audio=%s",
            volume_original * 100, volume_music * 100, has_video_audio,
        )
        return video_path

    finally:
        # Clean up temp files regardless of success/failure
        for tmp in [f for f in (audio_path, output_path) if f and os.path.exists(f)]:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def get_or_create_chat(user1, user2):
    """Obtiene o crea chat entre dos usuarios"""
    chat, created = ChatRoom.objects.get_or_create(
        participant1=min(user1, user2),
        participant2=max(user1, user2)
    )
    return chat

def get_user_chats(user):
    """Chats del usuario ordenados por última actividad"""
    return ChatRoom.objects.filter(
        Q(participant1=user) | Q(participant2=user)
    ).select_related('participant1', 'participant2').order_by('-updated_at')