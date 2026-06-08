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
from .models import Category, Video

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
    print(result, "--------------------")
    return result


def _run_ffprobe(*args, timeout: int = 120) -> str:
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
# Score mínimo para asignar categoría.
# Formula: score = hits * base_hit_score, so 1 hit = _BASE_HIT * _WEIGHT_TEXT.
# With lists of ~100 keywords a single hit used to give 1/100 = 0.01 (below 0.02).
# Now we use a fixed base per hit so even 1 match qualifies.
_BASE_HIT_SCORE = 0.05  # weight per keyword hit (before signal weight)
_MIN_SCORE      = 0.04  # minimum combined score to accept a category


def _category_scores_from_text(text: str) -> dict[str, float]:
    """
    Keyword matching. Score = number_of_hits * _BASE_HIT_SCORE * _WEIGHT_TEXT.
    Using a fixed per-hit weight (instead of hits/len) ensures that even a
    single keyword match in the description/transcript is enough to assign
    a category, regardless of how large the keyword list is.
    """
    if not text:
        return {}
    stemmed = _stem(text)
    scores: dict[str, float] = {}
    for cat_name, keywords in CATEGORY_KEYWORDS.items():
        if not keywords:
            continue
        hits = sum(1 for kw in keywords if _stem(kw) in stemmed)
        if hits > 0:
            scores[cat_name] = hits * _BASE_HIT_SCORE * _WEIGHT_TEXT
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
        print(model)
        print(preprocess)
        print(tokens)
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
) -> tuple[Optional[str], Optional[str]]:
    """
    Combina tres señales para determinar la categoría:
      1. Keyword matching en texto (transcript + tags + description)
      2. Objetos YOLO detectados → mapa a categoría
      3. CLIP similitud visual frame por frame

    Returns (category_name, raw_fallback_term):
      - category_name: matched existing category name (or None)
      - raw_fallback_term: best detected raw term to auto-create a category
        when category_name is None (e.g. top YOLO object or transcript word)
    """
    combined: dict[str, float] = {}

    def _merge(scores: dict[str, float]) -> None:
        for cat, score in scores.items():
            combined[cat] = combined.get(cat, 0.0) + score

    _merge(_category_scores_from_text(text))
    _merge(_category_scores_from_yolo(detected_objects))
    _merge(_category_scores_from_clip(frames))

    if combined:
        best_cat   = max(combined, key=combined.get)
        best_score = combined[best_cat]

        logger.info(
            "Category scores: %s",
            {k: round(v, 3) for k, v in sorted(combined.items(), key=lambda x: -x[1])},
        )

        if best_score >= _MIN_SCORE:
            return best_cat, None

        # Below threshold but we still have a best candidate — return it
        logger.info(
            "Best score %.4f below threshold %.4f — using best candidate: %s",
            best_score, _MIN_SCORE, best_cat,
        )
        return best_cat, None

    # Zero signal from all three systems — derive a raw fallback term
    logger.info("No category signal found — deriving raw fallback term")

    # Generic YOLO classes that appear in almost any video and carry no category meaning
    _YOLO_NOISE_CLASSES = {
        "person", "people", "man", "woman", "human", "face",
        "hand", "arm", "leg", "body",
        "car", "truck", "vehicle",  # too generic without context
    }

    # 1. Top YOLO object excluding noise classes
    if detected_objects:
        # Sort by confidence descending, skip noise classes
        candidates = sorted(
            ((obj, conf) for obj, conf in detected_objects.items()
             if obj.lower() not in _YOLO_NOISE_CLASSES),
            key=lambda x: x[1],
            reverse=True,
        )
        if candidates:
            top_obj = candidates[0][0]
            raw_term = top_obj.replace("_", " ").strip().title()
            logger.info("Fallback from YOLO object: %s", raw_term)
            return None, raw_term
        else:
            logger.info("All YOLO objects are noise classes (%s) — skipping YOLO fallback",
                        list(detected_objects.keys()))

    # 2. First meaningful word from transcript/description/tags
    if text:
        stop_words = {
            "de", "la", "el", "en", "y", "a", "que", "es", "se", "un", "una",
            "con", "por", "para", "los", "las", "del", "al", "le", "lo", "su",
            "the", "a", "an", "is", "in", "of", "and", "to", "it", "i",
        }
        words = [w.strip(".,!?;:\"'") for w in text.lower().split()]
        meaningful = [w for w in words if len(w) > 3 and w not in stop_words]
        if meaningful:
            raw_term = meaningful[0].title()
            logger.info("Fallback from transcript word: %s", raw_term)
            return None, raw_term

    return None, None


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
        print("++++++++++", segments, "---------reymanuel-----------")
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
    logger.info("NOTIFY DEBUG — BROADCAST_SECRET=%r", settings.BROADCAST_SECRET)
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
            headers={"X-Broadcast-Secret": settings.BROADCAST_SECRET},
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
        print(audio_result, "---------rey-----------")
        # ──────────────────────────────────────────────────────────────────
        # 5. Visual analysis (YOLO) — only if audio passed
        # ──────────────────────────────────────────────────────────────────
        if audio_result.nsfw_confidence < NSFW_CONFIDENCE_THRESHOLD:
            vision_result = process_vision(video_path, temp_dir)
            print(f"\n🔍 YOLO detected objects: {vision_result.detected_objects}\n")

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
    # 6a. Metadata NSFW — scan description + tags even when audio is silent
    _meta_text_parts = [video.description or ""]
    if isinstance(video.tags, list):
        _meta_text_parts.append(" ".join(video.tags))
    elif video.tags:
        _meta_text_parts.append(str(video.tags))
    _meta_text = " ".join(filter(None, _meta_text_parts))
    meta_conf, meta_triggers = score_nsfw_text(_meta_text) if _meta_text else (0.0, [])
    if meta_conf > 0:
        logger.info(
            "Metadata NSFW: confidence=%.2f, triggers=%s", meta_conf, meta_triggers
        )

    # Noisy-OR across all three modalities: audio transcript, vision, metadata text
    audio_conf = audio_result.nsfw_confidence
    vision_conf = vision_result.nsfw_confidence
    combined_confidence = min(
        1.0,
        1.0 - (1.0 - audio_conf) * (1.0 - vision_conf) * (1.0 - meta_conf),
    )

    is_safe = combined_confidence < NSFW_CONFIDENCE_THRESHOLD
    all_triggers = audio_result.nsfw_triggers + vision_result.nsfw_triggers + meta_triggers

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

        category_name, raw_fallback_term = detect_category_multi(
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
        elif raw_fallback_term:
            # Auto-create a new category from the raw detected term
            category_name = raw_fallback_term
            logger.info("Auto-creating new category from raw term: %s", category_name)
        else:
            # Absolute last resort — use "General"
            category_name = "General"
            logger.info("No signal found for video %d — assigning 'General'", video_id)

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
            # category_name is always set for safe videos (auto-created if needed)
            cat, created = Category.objects.get_or_create(
                name=category_name,
                defaults={"is_active": True},
            )
            if created:
                logger.info("New category created: '%s'", category_name)
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

        # ── 10a. Mix custom audio track into the video file (if provided) ─
        # NOTE: Server-side FFmpeg mixing is disabled — audio is handled
        # entirely client-side (TikTok style). The fields audio_track_url,
        # audio_trim_start, volume_music, volume_original are stored in the
        # DB and sent to the frontend, which plays the track on top of the
        # video using the Web Audio API / HTML Audio element.
        #
        # If server-side mixing is ever needed again, uncomment below:
        #
        # if video.audio_track_url and video.video:
        #     try:
        #         from .utils import mix_audio_into_video
        #         mixed = mix_audio_into_video(
        #             video_path=video.video.path,
        #             audio_url=video.audio_track_url,
        #             volume_original=video.volume_original,
        #             volume_music=video.volume_music,
        #             audio_trim_start=getattr(video, 'audio_trim_start', 0.0),
        #         )
        #         if not mixed:
        #             logger.warning("Audio mixing failed for video %d", video.id)
        #     except Exception as exc:
        #         logger.warning("Audio mixing raised an exception for video %d: %s", video.id, exc)

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

# ─────────────────────────────────────────────────────────────────────────────
# Generación IA — BytePlus Vision AI
# ─────────────────────────────────────────────────────────────────────────────

import base64 as _base64
import uuid as _uuid

logger_ai = get_task_logger(__name__)

_STYLE_PROMPTS = {
    "cinematic": "cinematic style, professional film quality, dramatic lighting, movie scene",
    "anime":     "anime style, vibrant colors, Studio Ghibli inspired, Japanese animation",
    "realistic": "photorealistic, high quality, 8k resolution, ultra detailed",
    "artistic":  "artistic style, digital painting, creative visual, masterpiece",
    "3d":        "3D render, high quality, tridimensional, CGI quality, Unreal Engine",
    "retro":     "retro style, vintage aesthetic, nostalgic, film grain, 1980s",
}


def _build_xai_client():
    """Devuelve un cliente OpenAI apuntando a la API de xAI (Grok Imagine)."""
    from openai import OpenAI
    api_key = getattr(settings, "XAI_API_KEY", "")
    return OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")


def _download_and_save_media(url: str, mime_type: str = "image/jpeg") -> str:
    """Descarga una URL externa, la guarda en MEDIA_ROOT y devuelve la ruta relativa /media/..."""
    import requests as _requests
    ext = mime_type.split("/")[-1].replace("jpeg", "jpg")
    filename = f"ai_generated/{_uuid.uuid4().hex}.{ext}"
    full_path = os.path.join(getattr(settings, "MEDIA_ROOT", "/tmp"), filename)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    api_key = getattr(settings, "XAI_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0",
    }
    resp = _requests.get(url, headers=headers, timeout=120, stream=True)
    resp.raise_for_status()
    with open(full_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=8192):
            fh.write(chunk)
    media_url = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")
    return f"{media_url}/{filename}"


def _save_b64_media(b64_data: str, mime_type: str = "image/png") -> str:
    ext = mime_type.split("/")[-1].replace("jpeg", "jpg")
    filename = f"ai_generated/{_uuid.uuid4().hex}.{ext}"
    full_path = os.path.join(getattr(settings, "MEDIA_ROOT", "/tmp"), filename)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "wb") as fh:
        fh.write(_base64.b64decode(b64_data))
    return f"{getattr(settings, 'MEDIA_URL', '/media/')}{filename}"


def _generate_image_xai(client, history_id, full_prompt, ref_b64, ref_mime):
    """
    Generación de imagen con Grok Imagine (xAI) — llamada síncrona.
    Devuelve la URL pública o None si falla.
    """
    from .models import AIGenerationHistory
    from django.conf import settings

    logger_ai.info("Grok image submit — has_ref=%s", bool(ref_b64))

    if getattr(settings, "AI_DRY_RUN", False):
        logger_ai.info("🧪 DRY RUN — simulando imagen generada")
        fake_url = "https://picsum.photos/seed/buzzy/512/512"
        AIGenerationHistory.objects.filter(id=history_id).update(status="completed", media_url=fake_url)
        logger_ai.info("✅ [DRY RUN] Imagen simulada — history_id=%s", history_id)
        return fake_url
    image_url = ""

    if ref_b64:
        # Con imagen de referencia: Image Editing endpoint
        try:
            import urllib.request, json as _json, ssl
            api_key = client.api_key
            body = _json.dumps({
                "model": "grok-imagine-image-quality",
                "prompt": full_prompt,
                "image": {"url": f"data:{ref_mime};base64,{ref_b64}"},
                "n": 1,
                "response_format": "url",
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.x.ai/v1/images/edits",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode("utf-8")
                logger_ai.error("Grok image edit HTTP %s: %s", http_err.code, err_body)
                raise
            logger_ai.info("Grok image edit resp: %s", str(data)[:300])
            image_url = data.get("data", [{}])[0].get("url", "")
        except Exception as exc:
            logger_ai.error("Grok image edit falló: %s", exc)
            AIGenerationHistory.objects.filter(id=history_id).update(status="failed")
            return None
    else:
        # Sin imagen de referencia: generación desde texto
        try:
            response = client.images.generate(
                model="grok-imagine-image",
                prompt=full_prompt,
                n=1,
                response_format="url",
            )
            logger_ai.info("Grok image generate resp: %s", str(response)[:300])
            image_url = response.data[0].url or ""
        except Exception as exc:
            logger_ai.error("Grok image generate falló: %s", exc)
            AIGenerationHistory.objects.filter(id=history_id).update(status="failed")
            return None

    if image_url:
        try:
            image_url = _download_and_save_media(image_url, "image/jpeg")
            logger_ai.info("Imagen descargada localmente: %s", image_url)
        except Exception as dl_exc:
            logger_ai.error("No se pudo descargar imagen localmente: %s", dl_exc)
            AIGenerationHistory.objects.filter(id=history_id).update(status="failed")
            return None
        AIGenerationHistory.objects.filter(id=history_id).update(
            status="completed", media_url=image_url,
        )
        # Descontar crédito solo cuando la imagen se generó exitosamente
        from .models import AIWallet, AIGenerationHistory as _H
        _hist = _H.objects.filter(id=history_id).select_related('user').first()
        if _hist:
            AIWallet.get_or_create_for(_hist.user).consume_image()
        logger_ai.info("✅ Imagen completada — history_id=%s url=%s", history_id, image_url)
    else:
        logger_ai.error("Grok image: no image_url en respuesta")
        AIGenerationHistory.objects.filter(id=history_id).update(status="failed")

    return image_url


def _generate_video_xai(client, history_id, full_prompt, duration, ref_b64=None, ref_mime=None):
    """
    Generación de video con Grok Imagine (xAI) — submit asíncrono + polling.
    Devuelve (video_url, generation_id) o (None, None) si falla en el submit.
    """
    from .models import AIGenerationHistory

    logger_ai.info("Grok video submit — duration=%s has_ref=%s", duration, bool(ref_b64))

    # from django.conf import settings
    # if getattr(settings, "AI_DRY_RUN", False):
    #     logger_ai.info("🧪 DRY RUN — simulando video generado")
    #     fake_id = "dry-run-fake-id-12345"
    #     AIGenerationHistory.objects.filter(id=history_id).update(byteplus_task_id=fake_id, status="processing")
    #     return None, fake_id

    try:
        import urllib.request, json as _json, ssl
        api_key = client.api_key
        payload = {
            "model": "grok-imagine-video",
            "prompt": full_prompt,
            "duration": 1,
            "aspect_ratio": "16:9",
            "resolution": "480p"
        }
        if ref_b64:
            payload["image"] = {"url": f"data:{ref_mime};base64,{ref_b64}"}
        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.x.ai/v1/videos/generations",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        generation_id = data.get("id") or data.get("request_id") or data.get("generation_id")
        logger_ai.info("Grok video job enviado — generation_id=%s resp=%s", generation_id, str(data)[:200])
    except Exception as exc:
        logger_ai.error("Grok video submit falló: %s", exc)
        AIGenerationHistory.objects.filter(id=history_id).update(status="failed")
        return None, None

    AIGenerationHistory.objects.filter(id=history_id).update(
        byteplus_task_id=generation_id,
        status="processing",
    )
    return None, generation_id


def _poll_video_xai(client, history_id, generation_id):
    """
    Consulta el estado de un video en generación con Grok Imagine.
    Devuelve (status_str, video_url_or_None).
    status_str: 'processing' | 'completed' | 'failed'
    """
    from django.conf import settings
    if getattr(settings, "AI_DRY_RUN", False):
        logger_ai.info("🧪 DRY RUN — simulando video completado")
        return "completed", "https://www.w3schools.com/html/mov_bbb.mp4"

    try:
        import urllib.request, json as _json, ssl
        api_key = client.api_key
        req = urllib.request.Request(
            f"https://api.x.ai/v1/videos/{generation_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        status = data.get("status", "processing")
        logger_ai.info("Grok video poll — generation_id=%s status=%s resp=%s", generation_id, status, str(data)[:300])

        if status == "done":
            video_url = data.get("video", {}).get("url", "")
            return "completed", video_url
        elif status in ("failed", "cancelled", "error"):
            return "failed", None
        else:
            return "processing", None
    except Exception as exc:
        logger_ai.warning("Grok video poll error: %s", exc)
        return "processing", None


@shared_task(
    bind=True,
    max_retries=36,
    default_retry_delay=10,
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=480,
    soft_time_limit=450,
)
def generate_ai_media(
    self,
    history_id: int,
    media_type: str,
    style_slug: str,
    duration: int = 6,
    ref_image_path: str = None,
    ref_mime: str = None,
):
    """
    IMAGEN → Grok Imagine (xAI) images/generations (síncrono)
    VIDEO  → Grok Imagine (xAI) videos/generations + polling con retries
    """
    from .models import AIGenerationHistory

    try:
        history = AIGenerationHistory.objects.get(id=history_id)
    except AIGenerationHistory.DoesNotExist:
        logger_ai.error("generate_ai_media: history %s no encontrado", history_id)
        return

    client         = _build_xai_client()
    style_addition = _STYLE_PROMPTS.get(style_slug, "")

    # Leer imagen de referencia desde disco y convertir a base64
    ref_b64 = None
    if ref_image_path:
        try:
            import base64 as _b64, os as _os
            with open(ref_image_path, "rb") as f:
                ref_b64 = _b64.b64encode(f.read()).decode("utf-8")
            logger_ai.info("ref_b64 cargado desde disco — path=%s size=%d", ref_image_path, len(ref_b64))
            # No borrar aquí — se borra después del submit exitoso para no perderlo en retries
        except FileNotFoundError:
            # Normal en retries de polling — el archivo ya fue borrado tras el submit
            logger_ai.info("ref_image_path ya eliminado (retry de polling) — continuando sin ref")
            ref_b64 = None
        except Exception as exc:
            logger_ai.error("Error leyendo ref_image_path=%s: %s", ref_image_path, exc)
            ref_b64 = None

    if ref_b64:
        full_prompt = history.prompt or "Edit this image as described"
    elif style_addition:
        full_prompt = f"{history.prompt}, {style_addition}"
    else:
        full_prompt = history.prompt or "high quality image"

    # ── IMAGEN: llamada síncrona, termina en esta ejecución ──────────────────
    if media_type == "image":
        _generate_image_xai(client, history_id, full_prompt, ref_b64, ref_mime)
        return

    # ── VIDEO: submit asíncrono + polling con retries ─────────────────────────
    if not history.byteplus_task_id:
        logger_ai.info(
            "Grok video submit — has_ref=%s ref_len=%s",
            bool(ref_b64), len(ref_b64) if ref_b64 else 0,
        )
        _, generation_id = _generate_video_xai(client, history_id, full_prompt, duration, ref_b64, ref_mime)
        if not generation_id:
            raise self.retry(countdown=10)
        # Submit exitoso — borrar archivo temporal (ya tenemos ref_b64 en memoria para el retry no aplica)
        if ref_image_path:
            try:
                import os as _os3
                if _os3.path.exists(ref_image_path):
                    _os3.unlink(ref_image_path)
            except Exception:
                pass
        history.byteplus_task_id = generation_id

    # ── Polling ───────────────────────────────────────────────────────────────
    poll_status, video_url = _poll_video_xai(client, history_id, history.byteplus_task_id)

    if poll_status == "processing":
        raise self.retry(countdown=15)

    if poll_status == "completed" and video_url:
        try:
            video_url = _download_and_save_media(video_url, "video/mp4")
            logger_ai.info("Video descargado localmente: %s", video_url)
        except Exception as dl_exc:
            logger_ai.error("No se pudo descargar video localmente: %s", dl_exc)
            AIGenerationHistory.objects.filter(id=history_id).update(status="failed")
            return
        AIGenerationHistory.objects.filter(id=history_id).update(
            status="completed", media_url=video_url,
        )
        # Descontar créditos solo cuando el video se generó exitosamente
        from .models import AIWallet, AIGenerationHistory as _H
        _hist = _H.objects.filter(id=history_id).select_related('user').first()
        if _hist:
            AIWallet.get_or_create_for(_hist.user).consume_video(duration)
        logger_ai.info("✅ Video completado — history_id=%s url=%s", history_id, video_url)
    else:
        logger_ai.error("❌ Grok video falló — status=%s", poll_status)
        AIGenerationHistory.objects.filter(id=history_id).update(status="failed")


@shared_task(bind=True, max_retries=0)
def moderate_ai_media(self, video_id: int) -> str:
    """
    Modera y categoriza un Video generado por IA (imagen o video corto).
    No requiere archivo físico — usa el prompt (description) para texto
    y descarga la imagen para análisis CLIP si está disponible.
    """
    from .models import Video, Category

    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        return f"Video {video_id} not found"

    if video.status != "active":
        return f"Video {video_id} skipped (status={video.status})"

    # 1. Moderación de texto — prompt del usuario
    prompt_text = video.description or ""
    text_conf, text_triggers = score_nsfw_text(prompt_text)
    is_safe = text_conf < NSFW_CONFIDENCE_THRESHOLD

    if not is_safe:
        safety_label = f"NSFW en prompt (confianza={text_conf:.0%}): " + ", ".join(text_triggers[:5])
        video.is_safe = False
        video.safety_label = safety_label
        video.status = "blocked"
        video.save(update_fields=["is_safe", "safety_label", "status"])
        logger.warning("AI media %d bloqueada — %s", video_id, safety_label)
        return f"Video {video_id} blocked: {safety_label}"

    # 2. Categorización desde el prompt
    category_name, raw_fallback = detect_category_multi(
        text=prompt_text,
        detected_objects={},
        frames=[],
    )
    if not category_name:
        category_name = raw_fallback or "General"

    cat, _ = Category.objects.get_or_create(name=category_name, defaults={"is_active": True})

    video.is_safe = True
    video.safety_label = "approved"
    video.category = cat
    video.save(update_fields=["is_safe", "safety_label", "category"])

    logger.info("AI media %d — safe, category=%s", video_id, category_name)
    return f"Video {video_id} moderated: category={category_name}"


@shared_task(name='apps.videos.tasks.expire_unopened_gifts')
def expire_unopened_gifts():
    from django.utils import timezone
    from datetime import timedelta
    from apps.videos.models import UserGift, VideoGift, StoryGift

    cutoff = timezone.now() - timedelta(days=30)

    user_count, _ = UserGift.objects.filter(is_seen=False, created_at__lt=cutoff).delete()
    video_count, _ = VideoGift.objects.filter(is_seen=False, created_at__lt=cutoff).delete()
    story_count, _ = StoryGift.objects.filter(is_seen=False, created_at__lt=cutoff).delete()

    logger.info(f'Gifts expirados: {user_count} de perfil, {video_count} de video, {story_count} de historia')
    return f'Expirados: {user_count} perfil, {video_count} video, {story_count} historia'
