from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import serve
from . import views
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
]

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]