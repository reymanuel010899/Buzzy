from django.db import models
from apps.users.models import User

class WalletModel(models.Model):
    WALLET_TYPES = (
        ('main', 'Main Wallet'),
        ('bonus', 'Bonus Wallet'),
        ('points', 'Points Wallet'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallets', null=True, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=5, default='DOP')

    pass_code = models.CharField(max_length=5)

    wallet_type = models.CharField(max_length=10, choices=WALLET_TYPES, default='main')

    bonus_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    blocked_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    total_deposited = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_withdrawn = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    last_transaction_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    version = models.IntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True,  blank=True, null=True)

    def __str__(self):
        return f"Wallet {self.id} - {self.user.username} - {self.balance}"

    class Meta:
        verbose_name = 'wallet'
        verbose_name_plural = 'wallets'
