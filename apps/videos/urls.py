from django.urls import path
from . import views
app_name = 'video'

urlpatterns = [
    path('api/list-home/', views.ListMediaApiView.as_view(), name='media-home'),
    path('api/upload/', views.VideoUploadView.as_view(), name='video-upload'),
    path('api/video/<int:id>/', views.VideoUploadView.as_view(), name='video-detail'),
]
