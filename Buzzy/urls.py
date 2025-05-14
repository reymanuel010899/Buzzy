from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.users.urls', namespace='users')),
    path('api/', include('apps.videos.urls', namespace='video')),
    path('api/', include('apps.markerplace.urls', namespace='markerplace')),
]

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]