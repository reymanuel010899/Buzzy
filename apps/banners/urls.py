from django.urls import path
from .views import ActiveBannerView

urlpatterns = [
    path('me/', ActiveBannerView.as_view(), name='active-banner'),
]
