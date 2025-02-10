from django.urls import path
from . import views
app_name = 'video'

urlpatterns = [
    path('api/list-home/', views.ListMediaApiView.as_view(), name='media-home' )
]
