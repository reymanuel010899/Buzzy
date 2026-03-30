from django.urls import path
from .views import HybridFeedAPIView

urlpatterns = [
    # Nueva ruta optimizada para el Feed con Redis
    path('feed/', HybridFeedAPIView.as_view(), name='hybrid-feed'),
]
