from django.urls import path
from .views import (
    SubscriptionPlanListView,
    CreateCheckoutSessionView,
    StripeWebhookView,
    StartCallView,
    CallInitiateView,
    CallEndView,
    AgoraCallWebhookView,
    CallAcceptView,
    VerifyCheckoutSessionView,
    SubscribersListView,
)

urlpatterns = [
    path('plans/', SubscriptionPlanListView.as_view(), name='subscription-plans'),
    path('create-checkout-session/', CreateCheckoutSessionView.as_view(), name='create-checkout-session'),
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
    path('start-call/', StartCallView.as_view(), name='start-call'),
    path('calls/initiate/', CallInitiateView.as_view(), name='call-initiate'),
    path('calls/accept/', CallAcceptView.as_view(), name='call-accept'),
    path('calls/end/', CallEndView.as_view(), name='call-end'),
    path('calls/agora-webhook/', AgoraCallWebhookView.as_view(), name='call-agora-webhook'),
    path('verify-session/', VerifyCheckoutSessionView.as_view(), name='verify-session'),
    path('<str:username>/', SubscribersListView.as_view(), name='subscribers-list'),
]
