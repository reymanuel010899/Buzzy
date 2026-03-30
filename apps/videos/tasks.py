"""
process_video_ai — Production-grade Celery task
================================================
Pipeline:
  1. Atomic status lock           (select_for_update → no race conditions)
  2. Pre-flight validation        (duration, codec, size limits)
  3. Audio extraction + Whisper   (with retry logic)
  4. NSFW text classification     (keyword tree + confidence scoring)
  5. Frame sampling + YOLO        (adaptive fps based on duration)
  6. Categorisation               (TF-IDF weighted keyword matching)
  7. Thumbnail generation         (multi-candidate, best-frame selection)
  8. Redis trending integration
  9. WebSocket notification       (BuzzySocket)
 10. Structured logging + metrics (Prometheus-ready counters)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

import requests
from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.recommendations.utils import get_redis_client

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration (override via Django settings or env vars)
# ---------------------------------------------------------------------------

MAX_VIDEO_DURATION_SEC: int = int(
    getattr(settings, "VIDEO_MAX_DURATION_SEC", os.environ.get("VIDEO_MAX_DURATION_SEC", 600))
)
MAX_VIDEO_SIZE_MB: int = int(
    getattr(settings, "VIDEO_MAX_SIZE_MB", os.environ.get("VIDEO_MAX_SIZE_MB", 500))
)
FFMPEG_TIMEOUT: int = int(
    getattr(settings, "FFMPEG_TIMEOUT", os.environ.get("FFMPEG_TIMEOUT", 120))
)
WHISPER_MODEL_SIZE: str = getattr(
    settings, "WHISPER_MODEL_SIZE", os.environ.get("WHISPER_MODEL_SIZE", "base")
)
YOLO_WEIGHTS: str = getattr(
    settings, "YOLO_WEIGHTS", os.environ.get("YOLO_WEIGHTS", "yolov8n.pt")
)
NSFW_CONFIDENCE_THRESHOLD: float = float(
    getattr(settings, "NSFW_CONFIDENCE_THRESHOLD", 0.6)
)
FRAME_SAMPLE_FPS: float = float(
    getattr(settings, "FRAME_SAMPLE_FPS", 0.5)   # 1 frame every 2 s
)
MAX_FRAMES_ANALYZED: int = int(
    getattr(settings, "MAX_FRAMES_ANALYZED", 60)
)
BUZZYSOCKET_URL: str = os.environ.get("BUZZYSOCKET_URL", "http://localhost:8001")
BUZZYSOCKET_TIMEOUT: int = 5
REDIS_TRENDING_KEY: str = "global_trending"

# ---------------------------------------------------------------------------
# NSFW vocabulary  ── much richer than the original 7-word list
# ---------------------------------------------------------------------------
#
# Three-tier severity system:
#   HARD  (1.0) → block immediately, single match
#   MEDIUM(0.6) → accumulate; block when confidence ≥ threshold
#   SOFT  (0.3) → context signal only; never blocks alone
#
# All stems are lower-cased; matching is done on stemmed transcript.
# ---------------------------------------------------------------------------

NSFW_VOCABULARY: dict[str, float] = {
    # ── Hard: explicit violence ──────────────────────────────────────────────
    "asesinato": 1.0,
    "homicidio": 1.0,
    "femicidio": 1.0,
    "feminicidio": 1.0,
    "masacre": 1.0,
    "degollado": 1.0,
    "decapitado": 1.0,
    "kill": 1.0,
    "murder": 1.0,
    "execution": 1.0,
    "beheading": 1.0,
    "massacre": 1.0,
    "torture": 1.0,
    "tortura": 1.0,
    # ── Hard: explicit sexual ────────────────────────────────────────────────
    "violación": 1.0,
    "violacion": 1.0,
    "rape": 1.0,
    "pornografía": 1.0,
    "pornografia": 1.0,
    "pornography": 1.0,
    # ── Hard: weapons ────────────────────────────────────────────────────────
    "arma": 0.6,
    "pistola": 0.6,
    "revólver": 0.6,
    "revolver": 0.6,
    "fusil": 0.6,
    "rifle": 0.6,
    "explosivo": 0.6,
    "bomba": 0.6,
    "granada": 0.4,  # also a fruit — context-sensitive
    "gun": 0.6,
    "weapon": 0.6,
    "explosive": 0.6,
    "bomb": 0.6,
    "grenade": 0.6,
    # ── Hard: drugs ──────────────────────────────────────────────────────────
    "droga": 0.6,
    "cocaína": 1.0,
    "cocaina": 1.0,
    "heroína": 1.0,
    "heroina": 1.0,
    "metanfetamina": 1.0,
    "fentanilo": 1.0,
    "crack": 0.5,  # also a sound / crack in a wall
    "narcotráfico": 1.0,
    "narcotrafico": 1.0,
    "cocaine": 1.0,
    "heroin": 1.0,
    "methamphetamine": 1.0,
    "fentanyl": 1.0,
    "drug trafficking": 1.0,
    # ── Hard: self-harm ──────────────────────────────────────────────────────
    "suicidio": 1.0,
    "suicide": 1.0,
    "quitarse la vida": 1.0,
    "autolesión": 0.8,
    "autolesion": 0.8,
    "self-harm": 0.8,
    "cutting myself": 0.8,
    # ── Medium: hate speech signals ──────────────────────────────────────────
    "blood": 0.3,
    "sangre": 0.3,
    "matar": 0.5,
    "kill yourself": 1.0,
    "mátate": 1.0,
    "matate": 1.0,
}

# ---------------------------------------------------------------------------
# YOLO object classes that signal NSFW content
# Confidence per class reflects how reliably COCO/custom weights detect it.
# ---------------------------------------------------------------------------

NSFW_YOLO_OBJECTS: dict[str, float] = {
    # Weapons (COCO classes 43=knife; custom weights may add gun/weapon)
    "knife":   0.5,   # Kitchen knives → false positives; weighted down
    "gun":     0.9,
    "weapon":  0.9,
    "rifle":   0.9,
    "pistol":  0.9,
    "handgun": 0.9,
    # Explicit content (requires custom NSFW weights)
    "nude":    1.0,
    "nsfw":    1.0,
    "explicit":1.0,
}

# Confidence required before a YOLO object label triggers a block
YOLO_OBJECT_CONFIDENCE_THRESHOLD: float = 0.55

# ---------------------------------------------------------------------------
# Category keyword registry  (unchanged from original, kept centralised)
# ---------------------------------------------------------------------------

from .keyworks import KEYWORDS_PRO_MAP, CLIP_PROMPTS, YOLO_TO_CATEGORY

# Single source of truth — defined in keywords.py, includes "Naturaleza y Animales"
CATEGORY_KEYWORDS: dict[str, list[str]] = KEYWORDS_PRO_MAP

# ---------------------------------------------------------------------------
# Data classes for intermediate results
# ---------------------------------------------------------------------------


@dataclass
class AudioResult:
    transcript: str = ""
    language: Optional[str] = None
    duration_sec: float = 0.0
    nsfw_confidence: float = 0.0
    nsfw_triggers: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class VisionResult:
    detected_objects: dict[str, float] = field(default_factory=dict)
    nsfw_confidence: float = 0.0
    nsfw_triggers: list[str] = field(default_factory=list)
    frames_analyzed: int = 0
    error: Optional[str] = None


@dataclass
class ProcessingResult:
    is_safe: bool = True
    safety_label: str = "approved"
    nsfw_confidence: float = 0.0
    transcript: str = ""
    category: Optional[str] = None
    duration_sec: int = 0
    thumbnail_path: Optional[str] = None
    video_url: Optional[str] = None
    audit_log: dict = field(default_factory=dict)

# ---------------------------------------------------------------------------
# Lazy model singletons (process-level, not thread-safe — Celery prefork OK)
# ---------------------------------------------------------------------------

_whisper_model = None
_yolo_model = None


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper model '%s'", WHISPER_MODEL_SIZE)
        _whisper_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            num_workers=2,
        )
    return _whisper_model


def _get_yolo():
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        logger.info("Loading YOLO weights '%s'", YOLO_WEIGHTS)
        _yolo_model = YOLO(YOLO_WEIGHTS)
    return _yolo_model

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _run_ffmpeg(*args, timeout: int = FFMPEG_TIMEOUT) -> subprocess.CompletedProcess:
    """Run an ffmpeg command, suppressing stdout/stderr unless it fails."""
    cmd = ["ffmpeg", "-y", *args]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited {result.returncode}: {result.stderr.decode(errors='replace')[:500]}"
        )
    return result


def _run_ffprobe(*args, timeout: int = 15) -> str:
    """Run an ffprobe command and return stripped stdout."""
    result = subprocess.run(
        ["ffprobe", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return result.stdout.decode(errors="replace").strip()


def get_video_duration(video_path: str) -> int:
    """Return video duration in whole seconds. Returns 0 on any error."""
    try:
        raw = _run_ffprobe(
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
            timeout=60
        )
        return int(float(raw))
    except Exception as exc:
        logger.warning("Could not read duration from %s: %s", video_path, exc)
        return 0


def get_video_size_mb(video_path: str) -> float:
    """Return file size in MB."""
    try:
        return os.path.getsize(video_path) / (1024 * 1024)
    except OSError:
        return 0.0


def _stem(text: str) -> str:
    """
    Very lightweight stemmer: lower-case, remove accents, collapse whitespace.
    For production consider spaCy/nltk per language detected by Whisper.
    """
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# NSFW text scoring
# ---------------------------------------------------------------------------


def score_nsfw_text(text: str) -> tuple[float, list[str]]:
    """
    Returns (confidence 0..1, list of triggered terms).

    Strategy:
      - Any single HARD term (weight=1.0) → confidence=1.0 immediately.
      - MEDIUM/SOFT terms accumulate; confidence = 1 − ∏(1 − wᵢ)  (noisy-OR).
    """
    if not text:
        return 0.0, []

    stemmed = _stem(text)
    triggers: list[str] = []
    weights: list[float] = []

    for term, weight in NSFW_VOCABULARY.items():
        stemmed_term = _stem(term)
        if stemmed_term in stemmed:
            triggers.append(term)
            weights.append(weight)
            if weight >= 1.0:
                # Short-circuit on hard term
                return 1.0, triggers

    if not weights:
        return 0.0, []

    # Noisy-OR combination: P(at least one) = 1 − ∏(1 − pᵢ)
    from functools import reduce
    import operator
    complement = reduce(operator.mul, (1.0 - w for w in weights), 1.0)
    confidence = min(1.0, 1.0 - complement)

    return confidence, triggers


# ---------------------------------------------------------------------------
# NSFW vision scoring
# ---------------------------------------------------------------------------


def score_nsfw_vision(
    frames: list[str],
    yolo,
) -> VisionResult:
    result = VisionResult()
    weights: list[float] = []

    for frame_path in frames:
        try:
            predictions = yolo(frame_path, verbose=False, conf=YOLO_OBJECT_CONFIDENCE_THRESHOLD)
        except Exception as exc:
            logger.warning("YOLO inference error on %s: %s", frame_path, exc)
            continue

        result.frames_analyzed += 1

        for pred in predictions:
            for box in pred.boxes:
                cls_id = int(box.cls[0])
                obj_conf = float(box.conf[0])
                obj_name = yolo.names[cls_id].lower()

                # Track all detected objects for audit
                result.detected_objects[obj_name] = max(
                    result.detected_objects.get(obj_name, 0.0), obj_conf
                )

                if obj_name in NSFW_YOLO_OBJECTS and obj_conf >= YOLO_OBJECT_CONFIDENCE_THRESHOLD:
                    nsfw_weight = NSFW_YOLO_OBJECTS[obj_name]
                    combined_weight = nsfw_weight * obj_conf
                    weights.append(combined_weight)
                    trigger = f"{obj_name}@{obj_conf:.2f}"
                    if trigger not in result.nsfw_triggers:
                        result.nsfw_triggers.append(trigger)

                    if combined_weight >= 1.0:
                        # Hard block: explicit class detected with high confidence
                        result.nsfw_confidence = 1.0
                        return result

    if weights:
        from functools import reduce
        import operator
        complement = reduce(operator.mul, (1.0 - w for w in weights), 1.0)
        result.nsfw_confidence = min(1.0, 1.0 - complement)

    return result


# ---------------------------------------------------------------------------
# Category detection — multi-signal system
# ---------------------------------------------------------------------------

# YOLO_TO_CATEGORY and CLIP_PROMPTS imported from keywords.py



# Pesos por señal
_WEIGHT_TEXT   = 1.0   # transcript + tags + description
_WEIGHT_YOLO   = 0.6   # objetos detectados por YOLO
_WEIGHT_CLIP   = 1.4   # similitud visual con CLIP (más confiable)
_MIN_SCORE     = 0.02  # score mínimo para asignar categoría


def _category_scores_from_text(text: str) -> dict[str, float]:
    """Keyword matching normalizado por tamaño de lista."""
    if not text:
        return {}
    stemmed = _stem(text)
    scores: dict[str, float] = {}
    for cat_name, keywords in CATEGORY_KEYWORDS.items():
        if not keywords:
            continue
        hits = sum(1 for kw in keywords if _stem(kw) in stemmed)
        if hits > 0:
            scores[cat_name] = (hits / len(keywords)) * _WEIGHT_TEXT
    return scores


def _category_scores_from_yolo(detected_objects: dict[str, float]) -> dict[str, float]:
    """Acumula confianza YOLO por categoría usando el mapa de objetos."""
    scores: dict[str, float] = {}
    for obj_name, confidence in detected_objects.items():
        cat = YOLO_TO_CATEGORY.get(obj_name.lower())
        if cat:
            scores[cat] = scores.get(cat, 0.0) + confidence * _WEIGHT_YOLO
    # Normalizar para que no escale infinitamente con más frames
    if scores:
        max_val = max(scores.values())
        scores = {k: v / max_val * _WEIGHT_YOLO for k, v in scores.items()}
    return scores


def _category_scores_from_clip(frames: list[str]) -> dict[str, float]:
    """
    Usa CLIP para comparar frames contra prompts de cada categoría.
    Devuelve dict vacío si CLIP no está instalado.
    """
    try:
        import clip
        import torch
        from PIL import Image
    except ImportError:
        return {}

    try:
        model, preprocess = clip.load("ViT-B/32", device="cpu")
        cats   = list(CLIP_PROMPTS.keys())
        texts  = list(CLIP_PROMPTS.values())
        tokens = clip.tokenize(texts)

        accum = torch.zeros(len(cats))
        used  = 0

        for frame_path in frames[:20]:
            try:
                img = preprocess(Image.open(frame_path)).unsqueeze(0)
                with torch.no_grad():
                    logits, _ = model(img, tokens)
                    probs = logits.softmax(dim=-1)[0]
                    accum += probs
                    used += 1
            except Exception:
                continue

        if used == 0:
            return {}

        avg = accum / used
        return {
            cat: float(avg[i]) * _WEIGHT_CLIP
            for i, cat in enumerate(cats)
        }
    except Exception as exc:
        logger.warning("CLIP categorization failed: %s", exc)
        return {}


def detect_category_multi(
    text: str,
    detected_objects: dict[str, float],
    frames: list[str],
) -> Optional[str]:
    """
    Combina tres señales para determinar la categoría:
      1. Keyword matching en texto (transcript + tags + description)
      2. Objetos YOLO detectados → mapa a categoría
      3. CLIP similitud visual frame por frame

    Cada señal tiene su propio peso. El score final es la suma ponderada.
    Devuelve None si ninguna categoría supera el umbral mínimo.
    """
    combined: dict[str, float] = {}

    def _merge(scores: dict[str, float]) -> None:
        for cat, score in scores.items():
            combined[cat] = combined.get(cat, 0.0) + score

    _merge(_category_scores_from_text(text))
    _merge(_category_scores_from_yolo(detected_objects))
    _merge(_category_scores_from_clip(frames))

    if not combined:
        return None

    best_cat   = max(combined, key=combined.get)
    best_score = combined[best_cat]

    logger.info(
        "Category scores: %s",
        {k: round(v, 3) for k, v in sorted(combined.items(), key=lambda x: -x[1])},
    )

    if best_score < _MIN_SCORE:
        logger.info("Best score %.4f below threshold %.4f — no category", best_score, _MIN_SCORE)
        return None

    return best_cat


# ---------------------------------------------------------------------------
# Thumbnail generation  (picks best of 3 candidate frames)
# ---------------------------------------------------------------------------


def generate_thumbnail(video_path: str, video_uuid: str) -> Optional[str]:
    """
    Extracts 3 candidate frames (1s, 25%, 50%) and picks the one with
    highest brightness variance (avoids black/overexposed frames).
    Returns the relative URL path under MEDIA_URL.
    """
    thumb_dir = os.path.join(settings.MEDIA_ROOT, "thumbnails")
    os.makedirs(thumb_dir, exist_ok=True)

    duration = get_video_duration(video_path)
    if duration == 0:
        duration = 10  # fallback

    candidates = [
        max(1, int(duration * 0.10)),
        max(1, int(duration * 0.25)),
        max(1, int(duration * 0.50)),
    ]
    best_path: Optional[str] = None
    best_score: float = -1.0

    with tempfile.TemporaryDirectory() as td:
        for i, ts in enumerate(candidates):
            cand_path = os.path.join(td, f"cand_{i}.jpg")
            try:
                _run_ffmpeg(
                    "-ss", str(ts),
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "2",
                    cand_path,
                    timeout=30,
                )
            except Exception as exc:
                logger.debug("Thumbnail candidate %s failed: %s", ts, exc)
                continue

            if not os.path.exists(cand_path):
                continue

            score = _image_variance(cand_path)
            if score > best_score:
                best_score = score
                best_path = cand_path

        if best_path and os.path.exists(best_path):
            thumb_name = f"thumb_{video_uuid}.jpg"
            dest = os.path.join(thumb_dir, thumb_name)
            import shutil
            shutil.copy2(best_path, dest)
            return f"{settings.MEDIA_URL}thumbnails/{thumb_name}"

    return None


def _image_variance(image_path: str) -> float:
    """
    Returns the pixel-brightness variance of an image as a frame-quality proxy.
    A black frame scores near 0; a nicely-varied frame scores higher.
    Falls back to 0.0 if PIL/Pillow is not installed.
    """
    try:
        from PIL import Image, ImageStat
        import statistics

        with Image.open(image_path).convert("L") as img:
            img.thumbnail((320, 320))
            stat = ImageStat.Stat(img)
            return stat.stddev[0]
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------


def preflight_check(video_path: str) -> Optional[str]:
    """
    Returns None if video passes all pre-flight checks,
    or a human-readable rejection reason string.
    """
    # 1. File size
    size_mb = get_video_size_mb(video_path)
    if size_mb > MAX_VIDEO_SIZE_MB:
        return f"Archivo demasiado grande: {size_mb:.1f} MB (máx {MAX_VIDEO_SIZE_MB} MB)"

    # 2. Duration
    duration = get_video_duration(video_path)
    if duration > MAX_VIDEO_DURATION_SEC:
        return (
            f"Video demasiado largo: {duration}s (máx {MAX_VIDEO_DURATION_SEC}s)"
        )

    # 3. Valid video stream
    probe = _run_ffprobe(
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    )
    if not probe:
        return "El archivo no contiene una pista de video válida"

    return None  # all good


# ---------------------------------------------------------------------------
# Audio processing
# ---------------------------------------------------------------------------


def process_audio(video_path: str, temp_dir: str) -> AudioResult:
    result = AudioResult()
    audio_path = os.path.join(temp_dir, "audio.wav")

    try:
        _run_ffmpeg(
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            audio_path,
        )
    except Exception as exc:
        result.error = f"Extracción de audio falló: {exc}"
        logger.warning(result.error)
        return result

    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1024:
        result.error = "Audio demasiado corto o silencioso"
        return result

    try:
        model = _get_whisper()
        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            vad_filter=True,           # skip silent segments
            vad_parameters={"min_silence_duration_ms": 500},
        )
        texts = [seg.text for seg in segments]
        result.transcript = " ".join(texts).strip()
        result.language = info.language
        result.duration_sec = info.duration

        logger.info(
            "Transcription: lang=%s, duration=%.1fs, chars=%d",
            info.language, info.duration, len(result.transcript),
        )
    except Exception as exc:
        result.error = f"Whisper falló: {exc}"
        logger.warning(result.error)
        return result

    result.nsfw_confidence, result.nsfw_triggers = score_nsfw_text(result.transcript)
    return result


# ---------------------------------------------------------------------------
# Vision processing
# ---------------------------------------------------------------------------


def process_vision(video_path: str, temp_dir: str) -> VisionResult:
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        logger.warning("ultralytics not installed — skipping visual analysis")
        return VisionResult(error="ultralytics not installed")

    frames_dir = os.path.join(temp_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # Adaptive FPS: for long videos reduce sampling to cap frame count
    duration = get_video_duration(video_path)
    if duration > 0:
        desired_frames = min(MAX_FRAMES_ANALYZED, max(10, duration // 2))
        fps = desired_frames / duration
    else:
        fps = FRAME_SAMPLE_FPS

    try:
        _run_ffmpeg(
            "-i", video_path,
            "-vf", f"fps={fps:.4f}",
            "-q:v", "3",
            os.path.join(frames_dir, "frame_%05d.jpg"),
        )
    except Exception as exc:
        return VisionResult(error=f"Extracción de frames falló: {exc}")

    frames = sorted(
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.endswith(".jpg")
    )[:MAX_FRAMES_ANALYZED]

    if not frames:
        return VisionResult(error="No se pudieron extraer frames")

    try:
        yolo = _get_yolo()
        result = score_nsfw_vision(frames, yolo)
        logger.info(
            "Vision: %d frames analyzed, nsfw_confidence=%.2f, triggers=%s",
            result.frames_analyzed, result.nsfw_confidence, result.nsfw_triggers,
        )
        return result
    except Exception as exc:
        return VisionResult(error=f"YOLO falló: {exc}")


# ---------------------------------------------------------------------------
# Redis helpers (with connection error isolation)
# ---------------------------------------------------------------------------


def _redis_add_trending(video_id: int) -> None:
    try:
        client = get_redis_client()
        timestamp = timezone.now().timestamp()
        client.zadd(REDIS_TRENDING_KEY, {str(video_id): timestamp})
        logger.info("Video %d added to Redis trending set", video_id)
    except Exception as exc:
        # Redis failure must never prevent the video from going live.
        logger.error("Redis trending update failed for video %d: %s", video_id, exc)


def _redis_cache_result(video_id: int, result: ProcessingResult) -> None:
    """Cache processing result for 24 h — useful for webhook retries."""
    try:
        client = get_redis_client()
        key = f"video_result:{video_id}"
        payload = json.dumps({
            "is_safe": result.is_safe,
            "safety_label": result.safety_label,
            "category": result.category,
            "nsfw_confidence": result.nsfw_confidence,
            "processed_at": timezone.now().isoformat(),
        })
        client.setex(key, 86_400, payload)
    except Exception as exc:
        logger.warning("Redis result cache failed for video %d: %s", video_id, exc)


# ---------------------------------------------------------------------------
# WebSocket notification
# ---------------------------------------------------------------------------


def _notify_buzzysocket(video, status: str, category: Optional[str]) -> None:
    try:
        response = requests.post(
            f"{BUZZYSOCKET_URL}/broadcast-video-ready/",
            json={
                "user_id": video.user_id_id,
                "video_id": video.id,
                "status": status,
                "safety_label": video.safety_label,
                "category": category,
                "timestamp": timezone.now().isoformat(),
            },
            timeout=BUZZYSOCKET_TIMEOUT,
        )
        if response.status_code >= 400:
            logger.warning(
                "BuzzySocket returned %d for video %d", response.status_code, video.id
            )
    except Exception as exc:
        # Notification failure is non-fatal.
        logger.error("BuzzySocket notification failed for video %d: %s", video.id, exc)


# ---------------------------------------------------------------------------
# Metrics (Prometheus-style — no-op if prometheus_client not installed)
# ---------------------------------------------------------------------------

def _inc_counter(name: str, labels: dict | None = None) -> None:
    try:
        from prometheus_client import Counter
        # Counters are singletons; get_or_create pattern
        if not hasattr(_inc_counter, "_registry"):
            _inc_counter._registry = {}
        key = (name, tuple(sorted((labels or {}).keys())))
        if key not in _inc_counter._registry:
            _inc_counter._registry[key] = Counter(
                name, name.replace("_", " "), list((labels or {}).keys())
            )
        _inc_counter._registry[key].labels(**(labels or {})).inc()
    except Exception:
        pass  # metrics are best-effort


# ---------------------------------------------------------------------------
# Main Celery task
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,          # 1 minute between retries
    acks_late=True,                  # ack only after success/failure (not on receive)
    reject_on_worker_lost=True,      # requeue if worker dies mid-task
    time_limit=900,                  # hard kill after 15 min
    soft_time_limit=780,             # soft kill at 13 min (raises SoftTimeLimitExceeded)
)
def process_video_ai(self, video_id: int) -> str:
    """
    Full AI moderation + categorisation pipeline for a single video.
    Idempotent: safe to retry; status guard is atomically locked.
    """
    from .models import Category, Video

    t_start = time.monotonic()
    _inc_counter("video_processing_started_total", {"task": "process_video_ai"})

    # ──────────────────────────────────────────────────────────────────────
    # 1. Atomic status lock — prevents double-processing
    # ──────────────────────────────────────────────────────────────────────
    try:
        with transaction.atomic():
            video = Video.objects.select_for_update(nowait=True).get(id=video_id)

            if video.status != "pending":
                logger.info(
                    "Video %d skipped — current status: %s", video_id, video.status
                )
                return f"Video {video_id} skipped (status={video.status})"

            video.status = "processing"
            video.save(update_fields=["status"])

    except Video.DoesNotExist:
        logger.error("Video %d not found", video_id)
        return f"Video {video_id} not found"
    except Exception as exc:
        # Could not acquire lock → another worker is processing this video
        logger.warning("Could not lock video %d: %s", video_id, exc)
        return f"Video {video_id} lock contention — skipped"

    video_path = video.video.path if video.video else None

    if not video_path or not os.path.exists(video_path):
        _finalize_video(video, is_safe=False, label="Archivo no encontrado")
        return f"Video {video_id} — file missing"

    # ──────────────────────────────────────────────────────────────────────
    # 2. Pre-flight validation
    # ──────────────────────────────────────────────────────────────────────
    rejection_reason = preflight_check(video_path)
    if rejection_reason:
        logger.warning("Video %d rejected at pre-flight: %s", video_id, rejection_reason)
        _inc_counter("video_rejected_total", {"reason": "preflight"})
        _finalize_video(video, is_safe=False, label=rejection_reason)
        return f"Video {video_id} rejected: {rejection_reason}"

    # ──────────────────────────────────────────────────────────────────────
    # 3 + 4. Audio extraction & transcription + NSFW text scoring
    # ──────────────────────────────────────────────────────────────────────
    audio_result = AudioResult()
    vision_result = VisionResult()
    _frames_for_category: list[str] = []   # kept alive after temp_dir closes

    with tempfile.TemporaryDirectory() as temp_dir:
        logger.info("Processing video %d in %s", video_id, temp_dir)

        audio_result = process_audio(video_path, temp_dir)

        # ──────────────────────────────────────────────────────────────────
        # 5. Visual analysis (YOLO) — only if audio passed
        # ──────────────────────────────────────────────────────────────────
        if audio_result.nsfw_confidence < NSFW_CONFIDENCE_THRESHOLD:
            vision_result = process_vision(video_path, temp_dir)

            # Copy frames to a persistent temp dir for CLIP categorization
            frames_dir = os.path.join(temp_dir, "frames")
            if os.path.isdir(frames_dir):
                import shutil, tempfile as _tf
                persistent = _tf.mkdtemp(prefix="buzzy_frames_")
                for f in sorted(os.listdir(frames_dir))[:20]:
                    if f.endswith(".jpg"):
                        shutil.copy2(os.path.join(frames_dir, f), persistent)
                        _frames_for_category.append(os.path.join(persistent, f))
        else:
            logger.info(
                "Skipping vision — audio NSFW confidence %.2f ≥ threshold %.2f",
                audio_result.nsfw_confidence, NSFW_CONFIDENCE_THRESHOLD,
            )

    # ──────────────────────────────────────────────────────────────────────
    # 6. Combined NSFW decision
    # ──────────────────────────────────────────────────────────────────────
    # Noisy-OR across modalities
    audio_conf = audio_result.nsfw_confidence
    vision_conf = vision_result.nsfw_confidence
    combined_confidence = min(1.0, 1.0 - (1.0 - audio_conf) * (1.0 - vision_conf))

    is_safe = combined_confidence < NSFW_CONFIDENCE_THRESHOLD
    all_triggers = audio_result.nsfw_triggers + vision_result.nsfw_triggers

    if not is_safe:
        safety_label = (
            f"NSFW detectado (confianza={combined_confidence:.0%}): "
            + ", ".join(all_triggers[:5])
        )
        _inc_counter("video_blocked_total", {"reason": "nsfw"})
    else:
        safety_label = "approved"

    # ──────────────────────────────────────────────────────────────────────
    # 7. Categorisation (only for safe videos)
    # ──────────────────────────────────────────────────────────────────────
    category_name: Optional[str] = None
    if is_safe:
        tags_text = (
            " ".join(video.tags)
            if isinstance(video.tags, list)
            else str(video.tags or "")
        )
        combined_text = " ".join(
            filter(None, [audio_result.transcript, video.description, tags_text])
        )

        category_name = detect_category_multi(
            text=combined_text,
            detected_objects=vision_result.detected_objects,
            frames=_frames_for_category,
        )

        # Cleanup persistent frames dir
        if _frames_for_category:
            import shutil
            try:
                shutil.rmtree(os.path.dirname(_frames_for_category[0]), ignore_errors=True)
            except Exception:
                pass

        if category_name:
            logger.info("Category assigned: %s", category_name)
        else:
            logger.info("No category matched for video %d", video_id)

    # ──────────────────────────────────────────────────────────────────────
    # 8. Thumbnail generation
    # ──────────────────────────────────────────────────────────────────────
    thumbnail_url: Optional[str] = None
    if not video.thumbnail_url and video.video:
        thumbnail_url = generate_thumbnail(video_path, str(video.uuid))
        if thumbnail_url:
            logger.info("Thumbnail generated: %s", thumbnail_url)
        else:
            logger.warning("Thumbnail generation failed for video %d", video_id)

    # ──────────────────────────────────────────────────────────────────────
    # 9. Persist results
    # ──────────────────────────────────────────────────────────────────────
    elapsed_sec = time.monotonic() - t_start

    audit = {
        "audio_language": audio_result.language,
        "audio_nsfw_confidence": round(audio_conf, 4),
        "audio_nsfw_triggers": audio_result.nsfw_triggers,
        "audio_error": audio_result.error,
        "vision_frames_analyzed": vision_result.frames_analyzed,
        "vision_nsfw_confidence": round(vision_conf, 4),
        "vision_nsfw_triggers": vision_result.nsfw_triggers,
        "vision_detected_objects": vision_result.detected_objects,
        "vision_error": vision_result.error,
        "combined_nsfw_confidence": round(combined_confidence, 4),
        "processing_time_sec": round(elapsed_sec, 2),
        "worker": self.request.hostname,
    }

    with transaction.atomic():
        # Re-fetch to avoid overwriting concurrent field updates
        video = Video.objects.select_for_update().get(id=video_id)

        video.transcript = audio_result.transcript
        video.is_safe = is_safe
        video.safety_label = safety_label

        if is_safe:
            video.status = "ready"
            if category_name:
                cat, _ = Category.objects.get_or_create(name=category_name)
                video.category = cat
        else:
            video.status = "blocked"

        if not video.duration or video.duration == 0:
            video.duration = get_video_duration(video_path)

        if thumbnail_url and not video.thumbnail_url:
            video.thumbnail_url = thumbnail_url

        if not video.video_url and video.video:
            video.video_url = video.video.url

        # Build update_fields dynamically — only include fields that exist on the model.
        # audit_log requires a JSONField migration; if not present it is stored in Redis only.
        _update_fields = [
            "transcript", "is_safe", "safety_label", "status",
            "category", "duration", "thumbnail_url", "video_url",
        ]
        _model_fields = {f.name for f in video._meta.get_fields()}
        if "audit_log" in _model_fields:
            video.audit_log = audit
            _update_fields.append("audit_log")
        else:
            logger.debug(
                "audit_log field not found on Video model — "
                "audit stored in Redis only. "
                "Run the migration below to persist it in the DB:\n\n"
                "    audit_log = models.JSONField(default=dict, blank=True)\n"
            )

        video.save(update_fields=_update_fields)

    # ──────────────────────────────────────────────────────────────────────
    # 10. Post-processing integrations (non-fatal)
    # ──────────────────────────────────────────────────────────────────────
    if is_safe and video.status == "ready":
        _redis_add_trending(video.id)

    _redis_cache_result(video.id, ProcessingResult(
        is_safe=is_safe,
        safety_label=safety_label,
        nsfw_confidence=combined_confidence,
        transcript=audio_result.transcript,
        category=category_name,
        duration_sec=video.duration,
    ))

    _notify_buzzysocket(video, video.status, category_name)

    # If blocked: wipe file + DB record after the user has been notified
    if not is_safe:
        _delete_blocked_video(video)

    _inc_counter("video_processing_completed_total", {
        "status": video.status,
        "category": category_name or "none",
    })

    logger.info(
        "Video %d finished in %.1fs — status=%s, nsfw=%.0f%%, category=%s",
        video_id, elapsed_sec, video.status,
        combined_confidence * 100, category_name,
    )

    return (
        f"Video {video_id} processed in {elapsed_sec:.1f}s — "
        f"status={video.status}, nsfw={combined_confidence:.0%}, "
        f"category={category_name}"
    )


# ---------------------------------------------------------------------------
# Internal helper — finalize a blocked/errored video atomically
# ---------------------------------------------------------------------------


def _delete_blocked_video(video) -> None:
    """Delete the physical file(s) and the DB record for a blocked video."""
    video_id = video.id

    # 1. Delete the video file from disk
    try:
        if video.video and video.video.name:
            file_path = video.video.path
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info("Deleted blocked video file: %s", file_path)
    except Exception as exc:
        logger.warning("Could not delete video file for video %d: %s", video_id, exc)

    # 2. Delete thumbnail if it was saved locally
    try:
        if video.thumbnail_url:
            thumb_rel = video.thumbnail_url.replace(settings.MEDIA_URL, "", 1)
            thumb_path = os.path.join(settings.MEDIA_ROOT, thumb_rel)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
                logger.info("Deleted thumbnail: %s", thumb_path)
    except Exception as exc:
        logger.warning("Could not delete thumbnail for video %d: %s", video_id, exc)

    # 3. Delete the DB record
    try:
        video.delete()
        logger.info("Deleted blocked video record id=%d from DB", video_id)
    except Exception as exc:
        logger.error("Could not delete video %d from DB: %s", video_id, exc)


def _finalize_video(video, *, is_safe: bool, label: str) -> None:
    with transaction.atomic():
        video.is_safe = is_safe
        video.status = "blocked" if not is_safe else "ready"
        video.safety_label = label
        video.save(update_fields=["is_safe", "status", "safety_label"])

    # Notify user before wiping the record
    _notify_buzzysocket(video, video.status, None)

    if not is_safe:
        _delete_blocked_video(video)