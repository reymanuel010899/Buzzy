from django.db import models
import uuid
from apps.users.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

class CurrencyModel(models.Model):

    CURRENCY_TYPES = (
        ('fiat', 'Fiat Currency'),
        ('crypto', 'Cryptocurrency'),
    )

    code = models.CharField(max_length=5, unique=True)  # Ej: USD, DOP, BTC
    name = models.CharField(max_length=50)              # Ej: US Dollar
    symbol = models.CharField(max_length=5)             # Ej: $, RD$, €
    type = models.CharField(max_length=10, choices=CURRENCY_TYPES, default='fiat')
    
    decimals = models.IntegerField(default=2)           # Ej: USD=2, BTC=8
    exchange_rate_to_usd = models.DecimalField(max_digits=20, decimal_places=8, default=1)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        verbose_name = 'Currency'
        verbose_name_plural = 'Currencies'

class WalletModel(models.Model):
    WALLET_TYPES = (
        ('main', 'Main Wallet'),
        ('bonus', 'Bonus Wallet'),
        ('points', 'Points Wallet'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallets', null=True, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tokens = models.PositiveIntegerField(default=0)  # New token balance for sending gifts
    currency = models.ForeignKey(CurrencyModel, on_delete=models.CASCADE, related_name='currency', null=True, blank=True)

    pass_code = models.CharField(max_length=18, default=uuid.uuid4, unique=True)


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


class TransactionModel(models.Model):
    TRANSACTION_TYPES = (
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('transfer', 'Transfer'),
    )

    TRANSACTION_STATUS = (
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    )

    wallet = models.ForeignKey(WalletModel, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=10, choices=TRANSACTION_STATUS, default='completed')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    payment_id = models.CharField(max_length=255, blank=True, null=True) # Stripe Session or Payment ID

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transaction {self.id} - {self.transaction_type} - {self.status} - {self.amount}"

    class Meta:
        verbose_name = 'transaction'
        verbose_name_plural = 'transactions'


@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    if created:
        # We ensure a default currency exists. Looking at CurrencyModel, 'USD' seems to be the default code.
        currency, _ = CurrencyModel.objects.get_or_create(
            code='USD',
            defaults={'name': 'US Dollar', 'symbol': '$', 'type': 'fiat'}
        )
        WalletModel.objects.create(
            user=instance,
            balance=0.00,
            tokens=100,  # Initial token bonus for new users
            currency=currency,
            wallet_type='main'
        )

@receiver(post_save, sender=TransactionModel)
def update_wallet_balance(sender, instance, created, **kwargs):
    if created and instance.status == 'completed':
        wallet = instance.wallet
        if instance.transaction_type == 'deposit':
            wallet.balance += instance.amount
        elif instance.transaction_type == 'withdrawal':
            wallet.balance -= instance.amount
        wallet.save()

class BankAccount(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bank_accounts')
    account_holder_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)
    
    # Encrypted fields
    encrypted_account_number = models.TextField()
    encrypted_routing_number = models.TextField(blank=True, null=True)
    
    # Metadata
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Bank Account'
        verbose_name_plural = 'Bank Accounts'

    def __str__(self):
        return f"{self.bank_name} - {self.account_holder_name}"

    @property
    def masked_account_number(self):
        from .utils import decrypt_data
        raw = decrypt_data(self.encrypted_account_number)
        if len(raw) > 4:
            return f"****{raw[-4:]}"
        return "****"
