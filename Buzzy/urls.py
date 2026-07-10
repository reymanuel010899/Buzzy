from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.http import HttpResponseForbidden
from . import views


def _block_direct_video(request, path):
    """Protected media (videos + audio tracks) must be fetched via signed
    /media-signed/ links only, so copied raw /media/ links can't be reused."""
    return HttpResponseForbidden("Direct access to this media is not allowed.")


urlpatterns = [
    path('admin/', admin.site.urls),
    path('',  views.HealthCheck.as_view(), name="check"),
    path('', include('apps.users.urls', namespace='users')),
    path('', include('apps.videos.urls', namespace='video')),
    path('', include('apps.wallet.urls', namespace='wallet')),
    path('', include('apps.markerplace.urls', namespace='markerplace')),
    path('api/subscriptions/', include('apps.subscriptions.urls')),
    path('api/ads/', include('apps.ads.urls')),
    path('api/recommendations/', include('apps.recommendations.urls')),
    path('api/banners/', include('apps.banners.urls')),
    path('', include('apps.referrals.urls', namespace='referrals')),
]

urlpatterns += [
    # Signed, expiring URLs for protected media (videos). Validated by the view.
    re_path(r'^media-signed/(?P<path>.*)$', views.serve_signed_media, name="signed-media"),

    # Direct access to uploaded videos ("contenido/") AND audio track FILES
    # ("audio_tracks/files/") is blocked — they must be requested through the signed
    # endpoint above so copied links can't be reused/redownloaded forever.
    # NOTE: only the MP3 files are protected. The COVERS ("audio_tracks/covers/") are
    # public lightweight images served unsigned (blocking them gave 403 → broken art).
    re_path(r'^media/(?P<path>contenido/.*)$', _block_direct_video),
    re_path(r'^media/(?P<path>audio_tracks/files/.*)$', _block_direct_video),

    # Everything else under /media/ (gifts, thumbnails, avatars, covers, ...) stays
    # public. Served with HTTP Range support so <video> streaming works on Android.
    re_path(r'^media/(?P<path>.*)$', views.serve_public_media),
]