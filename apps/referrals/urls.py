from django.urls import path
from . import views

app_name = 'referrals'

urlpatterns = [
    path('api/referrals/generate/', views.GenerateReferralTokenView.as_view(), name='generate'),
    path('api/referrals/stats/', views.ReferralStatsView.as_view(), name='stats'),
    # Página de aterrizaje del link — sirve HTML con detección de app + fallback Play Store
    path('join', views.join_redirect_view, name='join'),
]
