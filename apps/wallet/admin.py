from django.contrib import admin

from apps.wallet.models import CurrencyModel, TransactionModel, WalletModel

# Register your models here.
admin.site.register(CurrencyModel)
admin.site.register(WalletModel)
admin.site.register(TransactionModel)