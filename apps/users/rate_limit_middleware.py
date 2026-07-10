"""
Rate-limit middleware — sliding-window per (user/IP, path, method).

Rules:
  - Authenticated user  → key = user_id + path + method
  - Anonymous           → key = client_ip + path + method
  - Default limit       : 10 requests / 10 seconds
  - Exceeding the limit : 429 Too Many Requests (JSON)

Endpoints that need stricter or looser limits can be listed in
RATE_LIMIT_OVERRIDES inside settings.py:

    RATE_LIMIT_OVERRIDES = {
        "/api/login/":       {"limit": 5,  "window": 60},
        "/api/create-like/": {"limit": 30, "window": 10},
    }

Set RATE_LIMIT_ENABLED = False in settings.py to disable globally.
"""

import json
import time
import hashlib

from django.conf import settings
from django.http import JsonResponse


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_redis():
    """Return a Redis client reusing the django-redis connection pool."""
    try:
        from django_redis import get_redis_connection
        return get_redis_connection("default")
    except Exception:
        return None


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _rate_limit_key(request) -> str:
    if request.user and request.user.is_authenticated:
        identity = f"u:{request.user.pk}"
    else:
        identity = f"ip:{_client_ip(request)}"

    # Normalize path: strip trailing slash so /foo and /foo/ share the key
    path = request.path.rstrip("/") or "/"
    method = request.method.upper()

    raw = f"rl:{identity}:{method}:{path}"
    # Hash to keep Redis key short and safe
    return "rl:" + hashlib.sha256(raw.encode()).hexdigest()


# ── middleware ────────────────────────────────────────────────────────────────

class RateLimitMiddleware:
    """Sliding-window rate limiter backed by Redis."""

    DEFAULT_LIMIT = 10   # max requests
    DEFAULT_WINDOW = 10  # seconds

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, "RATE_LIMIT_ENABLED", True)
        self.overrides: dict = getattr(settings, "RATE_LIMIT_OVERRIDES", {})
        self._redis = None  # lazy

    def _get_limits(self, path: str):
        """Return (limit, window) for this path, checking overrides first."""
        # Exact match
        if path in self.overrides:
            cfg = self.overrides[path]
            return cfg.get("limit", self.DEFAULT_LIMIT), cfg.get("window", self.DEFAULT_WINDOW)
        # Prefix match (longest prefix wins)
        best = None
        for prefix, cfg in self.overrides.items():
            if path.startswith(prefix):
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, cfg)
        if best:
            cfg = best[1]
            return cfg.get("limit", self.DEFAULT_LIMIT), cfg.get("window", self.DEFAULT_WINDOW)
        return self.DEFAULT_LIMIT, self.DEFAULT_WINDOW

    def __call__(self, request):
        if not self.enabled:
            return self.get_response(request)

        # Skip Django admin, static, and media (raw AND signed). CRÍTICO: incluir
        # "/media-signed/" — el video/música firmados se sirven por ahí y ExoPlayer
        # hace MUCHAS peticiones Range del mismo archivo (streaming + seeks). Sin este
        # skip, superaban el límite (10 req/10s) → 429 → el video/música se trababa y
        # "parecía expirada". Los media firmados ya están protegidos por la firma HMAC.
        path = request.path
        if path.startswith(("/admin/", "/static/", "/media/", "/media-signed/")):
            return self.get_response(request)

        # Lazy Redis connection
        if self._redis is None:
            self._redis = _get_redis()

        # If Redis is unavailable, fail open (don't block requests)
        if self._redis is None:
            return self.get_response(request)

        limit, window = self._get_limits(path.rstrip("/") or "/")

        key = _rate_limit_key(request)
        now = time.time()
        window_start = now - window

        try:
            pipe = self._redis.pipeline()
            # Remove timestamps outside the current window
            pipe.zremrangebyscore(key, "-inf", window_start)
            # Count remaining
            pipe.zcard(key)
            # Add current request timestamp (score = timestamp, member = unique nano id)
            pipe.zadd(key, {f"{now:.6f}": now})
            # Expire key after window so Redis doesn't accumulate stale keys
            pipe.expire(key, window * 2)
            _, count, _, _ = pipe.execute()
        except Exception:
            # Redis error → fail open
            return self.get_response(request)

        remaining = max(0, limit - count - 1)

        if count >= limit:
            response = JsonResponse(
                {
                    "error": "Too many requests. Please slow down.",
                    "retry_after": window,
                },
                status=429,
            )
            response["Retry-After"] = str(window)
            response["X-RateLimit-Limit"] = str(limit)
            response["X-RateLimit-Remaining"] = "0"
            response["X-RateLimit-Window"] = str(window)
            return response

        response = self.get_response(request)
        response["X-RateLimit-Limit"] = str(limit)
        response["X-RateLimit-Remaining"] = str(remaining)
        response["X-RateLimit-Window"] = str(window)
        return response
