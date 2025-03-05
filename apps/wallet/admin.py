from django.contrib import admin

from apps.wallet.models import CurrencyModel, TransactionModel, WalletModel, TokenPackage, BankAccount, GlobalSettings

# Register your models here.
admin.site.register(CurrencyModel)
admin.site.register(WalletModel)
admin.site.register(TransactionModel)
admin.site.register(TokenPackage)
admin.site.register(BankAccount)
admin.site.register(GlobalSettings)