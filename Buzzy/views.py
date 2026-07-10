import mimetypes
import os
import re

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .media_signing import verify_media_signature


class HealthCheck(APIView):
    def get(self, request):
        return Response({"message": "Successful"}, status=status.HTTP_200_OK)


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def serve_signed_media(request, path):
    """
    Serve a media file only if the request carries a valid, non-expired signature.

    Plain /media/ links for protected content are blocked elsewhere; clients get
    /media-signed/<path>?expires=..&sig=.. instead, which dies after a short TTL so
    a copied link can't be downloaded/shared forever.

    HTTP Range requests are honored so video seeking/streaming works (206 Partial
    Content), regardless of whether we're behind the dev server or gunicorn.
    """
    expires = request.GET.get("expires")
    sig = request.GET.get("sig")

    if not verify_media_signature(path, expires, sig):
        return HttpResponseForbidden("Invalid or expired media link.")

    # Resolve the file safely inside MEDIA_ROOT (block path traversal).
    media_root = os.path.realpath(settings.MEDIA_ROOT)
    full_path = os.path.realpath(os.path.join(media_root, path))
    if not full_path.startswith(media_root + os.sep) or not os.path.isfile(full_path):
        raise Http404("Media not found.")

    file_size = os.path.getsize(full_path)
    content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
    range_header = request.META.get("HTTP_RANGE", "")
    match = _RANGE_RE.match(range_header) if range_header else None

    if match:
        start_str, end_str = match.groups()
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            resp = HttpResponse(status=416)  # Range Not Satisfiable
            resp["Content-Range"] = f"bytes */{file_size}"
            return resp
        length = end - start + 1
        f = open(full_path, "rb")
        f.seek(start)
        response = FileResponse(f, status=206, content_type=content_type)
        response["Content-Length"] = str(length)
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        # FileResponse streams the whole file by default; cap it to the range.
        response.streaming_content = _file_range_iterator(f, length)
    else:
        response = FileResponse(open(full_path, "rb"), content_type=content_type)
        response["Content-Length"] = str(file_size)

    response["Accept-Ranges"] = "bytes"
    # These links are per-user and expiring: never let a shared cache keep them.
    response["Cache-Control"] = "private, max-age=0, no-store"
    return response


def serve_public_media(request, path):
    """
    Serve a public media file (gifts, thumbnails, avatars, covers, ...) WITH HTTP
    Range support so the HTML5 <video> element can stream/seek properly.

    Django's bundled `static.serve` ignores Range headers and always returns the
    whole file with 200, which makes Android's WebView freeze on <video> playback.
    This honours Range (206 Partial Content) so streaming works on every client.
    """
    media_root = os.path.realpath(settings.MEDIA_ROOT)
    full_path = os.path.realpath(os.path.join(media_root, path))
    if not full_path.startswith(media_root + os.sep) or not os.path.isfile(full_path):
        raise Http404("Media not found.")

    file_size = os.path.getsize(full_path)
    content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
    range_header = request.META.get("HTTP_RANGE", "")
    match = _RANGE_RE.match(range_header) if range_header else None

    if match:
        start_str, end_str = match.groups()
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            resp = HttpResponse(status=416)  # Range Not Satisfiable
            resp["Content-Range"] = f"bytes */{file_size}"
            return resp
        length = end - start + 1
        f = open(full_path, "rb")
        f.seek(start)
        response = FileResponse(f, status=206, content_type=content_type)
        response["Content-Length"] = str(length)
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response.streaming_content = _file_range_iterator(f, length)
    else:
        response = FileResponse(open(full_path, "rb"), content_type=content_type)
        response["Content-Length"] = str(file_size)

    response["Accept-Ranges"] = "bytes"
    # Public, cacheable assets (gifts/thumbnails change rarely).
    response["Cache-Control"] = "public, max-age=86400"
    return response


def _file_range_iterator(file_obj, length, chunk_size=8192):
    """Yield at most `length` bytes from an already-seeked file object."""
    remaining = length
    while remaining > 0:
        chunk = file_obj.read(min(chunk_size, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        yield chunk
    file_obj.close()