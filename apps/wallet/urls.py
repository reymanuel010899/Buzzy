from django.urls import path
from . import views
app_name = 'wallet'

urlpatterns = [
    path('api/get-wallet/', views.GetWalletApiVIew.as_view(), name='get-wallet'),
    path('api/wallet/account-status/', views.StripeAccountStatusView.as_view(), name='get-wallet'),
    path('api/create-transactions/', views.CreateTransationsApiView.as_view(), name='create-transactions'),
    path('api/buy-tokens/', views.BuyTokensApiView.as_view(), name='buy-tokens'),
    path('api/create-deposit-session/', views.CreateDepositSessionView.as_view(), name='create-deposit-session'),
    path('api/wallet/verify-deposit-session/', views.VerifyDepositSessionView.as_view(), name='verify-deposit-session'),
    path('api/wallet/withdraw-funds/', views.WithdrawFundsView.as_view(), name='withdraw-funds'),
    path('api/wallet/bank-accounts/', views.BankAccountListCreateView.as_view(), name='bank-accounts-list-create'),
    path('api/wallet/bank-accounts/<int:pk>/', views.BankAccountDeleteView.as_view(), name='bank-accounts-delete'),
    path('api/wallet/token-packages/', views.TokenPackageListView.as_view(), name='token-packages-list'),
    path('api/wallet/calculate-token-price/', views.CalculateTokenPriceApiView.as_view(), name='calculate-token-price'),
]
