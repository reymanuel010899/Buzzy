"""
Signed media URLs with expiration.

Videos are served from the local filesystem. A plain `/media/...` link is public
and permanent, so anyone can copy it and download/share the file forever. To make
stolen links useless, video URLs are handed to clients as
`/media-signed/<path>?expires=<unix_ts>&sig=<hmac>` and expire after a short TTL.

The signature is an HMAC-SHA256 over "<path>:<expires>" keyed with SECRET_KEY, so
it cannot be forged without the server secret, and the path cannot be swapped.
"""

import hashlib
import hmac
import time
from typing import Optional, Union
from urllib.parse import quote

from django.conf import settings

# Default lifetime of a signed media link, in seconds (6 horas). 20 min era muy
# poco: en una app tipo TikTok el usuario tiene la app abierta mucho rato y las URLs
# (firmadas al cargar el feed y precargadas en ExoPlayer) expiraban → 403 Forbidden
# al reproducir. 6h cubre sesiones largas sin que las URLs robadas duren demasiado.
DEFAULT_MEDIA_TTL = 6 * 60 * 60


def _normalize_path(path: str) -> str:
    """Return the storage-relative path (no leading slash, no /media/ prefix).

    Tolerant of absolute URLs and already-signed paths so we can re-sign legacy
    values stored in the DB: an old row may hold a full
    "https://host/media/audio_tracks/x.mp3" URL. We strip the host, the
    "/media[-signed]/" prefix and any query string, leaving "audio_tracks/x.mp3".
    """
    if not path:
        return ""
    # Drop scheme+host if it's an absolute URL, and any query string (old signature).
    if path.startswith("http"):
        from urllib.parse import urlparse
        path = urlparse(path).path
    elif "?" in path:
        path = path.split("?", 1)[0]
    # Strip a leading "/media-signed/", MEDIA_URL ("/media/"), or a bare slash.
    media_url = getattr(settings, "MEDIA_URL", "/media/")
    for prefix in ("/media-signed/", media_url):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    return path.lstrip("/")


def _compute_sig(rel_path: str, expires: int) -> str:
    message = f"{rel_path}:{expires}".encode("utf-8")
    secret = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def sign_media_path(path: str, ttl: int = DEFAULT_MEDIA_TTL) -> str:
    """
    Build a signed, expiring URL for a media file.

    `path` may be a relative storage path ("contenido/x.mp4"), a "/media/..." path,
    or an absolute URL. Empty input is returned unchanged. An absolute URL pointing
    at OUR OWN media (its path contains "/media/" or "/media-signed/") is re-signed —
    this lets us re-sign legacy DB rows that stored a full crude URL. A truly external
    URL (different host, no /media/ path) is returned unchanged.
    Returns a root-relative URL like "/media-signed/contenido/x.mp4?expires=..&sig=..".
    """
    if not path:
        return path

    # Absolute URL: only re-sign if it's one of our own media paths; otherwise leave
    # external links (e.g. third-party audio) untouched.
    if path.startswith("http"):
        from urllib.parse import urlparse
        _p = urlparse(path).path
        if "/media/" not in _p and "/media-signed/" not in _p:
            return path  # external URL, not ours → don't sign

    rel_path = _normalize_path(path)
    if not rel_path:
        return path

    expires = int(time.time()) + int(ttl)
    sig = _compute_sig(rel_path, expires)
    # quote the path but keep slashes so the route still matches per-segment.
    encoded = quote(rel_path, safe="/")
    return f"/media-signed/{encoded}?expires={expires}&sig={sig}"


def verify_media_signature(rel_path: str, expires: Union[str, int, None], sig: Optional[str]) -> bool:
    """Return True only if the signature is valid AND not expired."""
    if not sig or expires is None:
        return False
    try:
        expires_int = int(expires)
    except (TypeError, ValueError):
        return False
    if expires_int < int(time.time()):
        return False  # expired
    expected = _compute_sig(_normalize_path(rel_path), expires_int)
    # constant-time comparison to avoid timing attacks
    return hmac.compare_digest(expected, sig)
