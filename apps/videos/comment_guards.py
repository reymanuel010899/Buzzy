"""
Comment spam & plagiarism protection — Phase 1
================================================
Three independent layers, all using Redis:

  1. Rate limiting   — 5/min · 30/hour · 100/day per user
  2. Cooldown        — 10 s between comments on the same video (5 s for replies)
  3. Deduplication   — same content hash blocked for 24 h per user
"""
import hashlib
from typing import Optional
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework import status


# ── Limits ────────────────────────────────────────────────────────────────────
RATE_LIMITS = [
    ("1m",  60,       5),    # 5 per minute
    ("1h",  3_600,   30),    # 30 per hour
    ("1d",  86_400, 100),    # 100 per day
]

COOLDOWN_SAME_VIDEO  = 5    # seconds — new top-level comment on same video
COOLDOWN_REPLY       = 5    # seconds — reply to a comment
DUPLICATE_TTL        = 86_400  # 24 h — block identical content


def _uid(user) -> int:
    return user.id


# ── 1. Rate limiting (sliding counter) ───────────────────────────────────────
def check_rate_limits(user) -> Optional[Response]:
    uid = _uid(user)
    for label, window, limit in RATE_LIMITS:
        key = f"comment:rate:{uid}:{label}"
        count = cache.get(key, 0)
        if count >= limit:
            return Response(
                {"error": f"Estás comentando demasiado rápido. Límite: {limit} por {label}."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
    return None


def increment_rate_counters(user):
    uid = _uid(user)
    for label, window, _ in RATE_LIMITS:
        key = f"comment:rate:{uid}:{label}"
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window)


# ── 2. Per-video cooldown ─────────────────────────────────────────────────────
def check_cooldown(user, video_id, is_reply: bool) -> Optional[Response]:
    uid = _uid(user)
    seconds = COOLDOWN_REPLY if is_reply else COOLDOWN_SAME_VIDEO
    key = f"comment:cooldown:{uid}:{video_id}"
    if cache.get(key):
        return Response(
            {"error": f"Espera {seconds} segundos antes de comentar de nuevo en este video."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    return None


def set_cooldown(user, video_id, is_reply: bool):
    uid = _uid(user)
    seconds = COOLDOWN_REPLY if is_reply else COOLDOWN_SAME_VIDEO
    key = f"comment:cooldown:{uid}:{video_id}"
    cache.set(key, 1, timeout=seconds)


# ── 3. Content deduplication (hash) ──────────────────────────────────────────
def _content_hash(content: str) -> str:
    return hashlib.sha256(content.lower().strip().encode()).hexdigest()


def check_duplicate(user, content: str) -> Optional[Response]:
    if not content or not content.strip():
        return None
    uid = _uid(user)
    h = _content_hash(content)
    key = f"comment:dup:{uid}:{h}"
    if cache.get(key):
        return Response(
            {"error": "Ya enviaste este mismo comentario recientemente."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    return None


def register_content_hash(user, content: str):
    if not content or not content.strip():
        return
    uid = _uid(user)
    h = _content_hash(content)
    key = f"comment:dup:{uid}:{h}"
    cache.set(key, 1, timeout=DUPLICATE_TTL)


# ── Public entry point ────────────────────────────────────────────────────────
def run_comment_guards(user, video_id, content: str, is_reply: bool) -> Optional[Response]:
    """
    Run all guards in order. Returns a Response with error on first violation,
    or None if everything passes.
    Call `commit_comment_guards` AFTER the comment is successfully saved.
    """
    error = check_rate_limits(user)
    if error:
        return error

    error = check_cooldown(user, video_id, is_reply)
    if error:
        return error

    return None


def commit_comment_guards(user, video_id, content: str, is_reply: bool):
    """Call this once the comment has been persisted successfully."""
    increment_rate_counters(user)
    set_cooldown(user, video_id, is_reply)
