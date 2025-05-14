from django.urls import path
from . import views
app_name = 'video'

urlpatterns = [
    path('video/list-home/', views.ListMediaApiView.as_view(), name='media-home'),
    path('video/upload/', views.VideoUploadView.as_view(), name='video-upload'),
    path('video/video/<int:id>/', views.VideoUploadView.as_view(), name='video-detail'),
]
