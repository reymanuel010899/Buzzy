from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views
from .premium_views import (
    PremiumStatusView, PremiumCheckoutView,
    PremiumCancelView, PremiumVerifyView, premium_webhook,
)

app_name = 'users'

urlpatterns = [
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'), 
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),  
    path('api/register/', views.RegisterView.as_view(), name='register'),
    path('api/login/', views.LoginView.as_view(), name='login'),
    path('api/google/login/', views.GoogleLoginView.as_view(), name='google-login'),
    path('api/google/register/', views.GoogleRegisterView.as_view(), name='google-register'),
    path('api/logout/', views.LogoutView.as_view(), name='logout'),
    path('api/get-user/<str:username>/', views.DetaildUser.as_view(), name='get-user'),
    path('api/get-media-user/<str:username>/', views.MediaByUser.as_view(), name='get-media-user'),
    path('api/save-availability-user/', views.SaveAvailabilityView.as_view(), name='save-availability-user'),
    path('api/get-availability-user/', views.GetAvailabilityView.as_view(), name='get-availability-user'),
    # Social OAuth
    path('api/social/init/<str:platform>/', views.SocialOAuthInitView.as_view(), name='social-oauth-init'),
    path('api/social/callback/<str:platform>/', views.SocialOAuthCallbackView.as_view(), name='social-oauth-callback'),
    path('api/social/accounts/', views.SocialAccountStatusView.as_view(), name='social-accounts'),
    path('api/social/disconnect/<str:platform>/', views.SocialAccountDisconnectView.as_view(), name='social-disconnect'),
    path('api/social/refresh/', views.SocialAccountRefreshView.as_view(), name='social-refresh'),
    path('api/update-profile/', views.UpdateProfileView.as_view(), name='update-profile'),
    path('api/availability-status/<str:username>/', views.UserAvailabilityStatusView.as_view(), name='availability-status'),
    path('api/chat-privacy/', views.ChatPrivacyStatusView.as_view(), name='chat-privacy-status'),
    path('api/chat-privacy/pin/', views.ChatPrivacyPinView.as_view(), name='chat-privacy-pin'),
    path('api/verify-pin/', views.VerifyChatPinView.as_view(), name='verify-chat-pin'),
    
    # Language preference
    path('api/user/language/', views.LanguageUpdateView.as_view(), name='user-language'),

    # Buzzy Premium (platform subscription)
    path('api/premium/status/', PremiumStatusView.as_view(), name='premium-status'),
    path('api/premium/checkout/', PremiumCheckoutView.as_view(), name='premium-checkout'),
    path('api/premium/verify/', PremiumVerifyView.as_view(), name='premium-verify'),
    path('api/premium/cancel/', PremiumCancelView.as_view(), name='premium-cancel'),
    path('api/premium/webhook/', premium_webhook, name='premium-webhook'),

    # Password Reset
    path('api/auth/forgot-password/', views.ForgotPasswordView.as_view(), name='forgot-password'),
    path('api/auth/verify-code/', views.VerifyCodeView.as_view(), name='verify-code'),
    path('api/auth/reset-password/', views.PasswordResetView.as_view(), name='reset-password'),

    # Phone Verification
    path('api/auth/verify-phone/', views.VerifyPhoneView.as_view(), name='verify-phone'),

    # FCM Device Registration
    path('api/auth/register-device/', views.RegisterDeviceView.as_view(), name='register-device'),
]
