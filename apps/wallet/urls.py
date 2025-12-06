from django.urls import path
from . import views
app_name = 'wallet'

urlpatterns = [
    path('api/get-wallet/', views.GetWalletApiVIew.as_view(), name='get-wallet'),
    path('api/create-transactions/', views.CreateTransationsApiView.as_view(), name='create-transactions'),
]
