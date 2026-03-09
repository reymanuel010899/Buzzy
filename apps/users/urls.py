from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

app_name = 'users'

urlpatterns = [
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'), 
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),  
    path('api/register/', views.RegisterView.as_view(), name='register'),
    path('api/login/', views.LoginView.as_view(), name='login'),
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
    path('api/update-profile/', views.UpdateProfileView.as_view(), name='update-profile'),
    path('api/availability-status/<str:username>/', views.UserAvailabilityStatusView.as_view(), name='availability-status'),
]
