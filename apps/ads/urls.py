from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AdCampaignViewSet, AdAnalyticsViewSet
from .webhook import stripe_webhook

router = DefaultRouter()
router.register(r'campaigns', AdCampaignViewSet, basename='ad-campaign')
router.register(r'analytics', AdAnalyticsViewSet, basename='ad-analytics')

urlpatterns = [
    path('', include(router.urls)),
    path('webhook/stripe/', stripe_webhook, name='ads-stripe-webhook'),
]
