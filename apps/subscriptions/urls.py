from django.urls import path
from .views import (
    SubscriptionPlanListView,
    CreateCheckoutSessionView,
    StripeWebhookView,
    StartCallView,
)

urlpatterns = [
    path('plans/', SubscriptionPlanListView.as_view(), name='subscription-plans'),
    path('create-checkout-session/', CreateCheckoutSessionView.as_view(), name='create-checkout-session'),
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
    path('start-call/', StartCallView.as_view(), name='start-call'),
]
