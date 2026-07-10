from django.urls import path
from .views import HybridFeedAPIView, FollowingFeedAPIView

urlpatterns = [
    # Nueva ruta optimizada para el Feed con Redis
    path('feed/', HybridFeedAPIView.as_view(), name='hybrid-feed'),
    # Timeline cronológico de las cuentas que el usuario sigue (tab "Seguidos")
    path('following/', FollowingFeedAPIView.as_view(), name='following-feed'),
]
