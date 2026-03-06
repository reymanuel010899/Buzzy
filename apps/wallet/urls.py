from django.urls import path
from . import views
app_name = 'wallet'

urlpatterns = [
    path('api/get-wallet/', views.GetWalletApiVIew.as_view(), name='get-wallet'),
    path('api/create-transactions/', views.CreateTransationsApiView.as_view(), name='create-transactions'),
    path('api/buy-tokens/', views.BuyTokensApiView.as_view(), name='buy-tokens'),
    path('api/create-deposit-session/', views.CreateDepositSessionView.as_view(), name='create-deposit-session'),
    path('api/withdraw-funds/', views.WithdrawFundsView.as_view(), name='withdraw-funds'),
]
