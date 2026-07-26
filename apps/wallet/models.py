from django.db import models
import uuid
from apps.users.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from dateutil.relativedelta import relativedelta

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

    #wallet_type = models.CharField(max_length=10, choices=WALLET_TYPES, default='main')

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
    
    # Optional link to bank account for withdrawals
    bank_account = models.ForeignKey('BankAccount', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')

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
        import uuid
        # We ensure a default currency exists. Looking at CurrencyModel, 'USD' seems to be the default code.
        currency, _ = CurrencyModel.objects.get_or_create(
            code='USD',
            defaults={'name': 'US Dollar', 'symbol': '$', 'type': 'fiat'}
        )
        
        country_code = getattr(instance.country, 'code', '') if hasattr(instance, 'country') and instance.country else ""
        pass_code = f"{country_code}{str(uuid.uuid4())[:8]}".upper()
        
        WalletModel.objects.create(
            user=instance,
            balance=0.00,
            tokens=100,  # Initial token bonus for new users
            pass_code=pass_code,
            currency=currency,
            wallet_type='main'
        )

@receiver(post_save, sender=TransactionModel)
def update_wallet_balance(sender, instance, created, **kwargs):
    # Only auto-credit deposits — withdrawals and transfers are already
    # deducted by the calling view before the transaction is created,
    # so we must NOT touch the balance here for those types.
    if created and instance.status == 'completed' and instance.transaction_type == 'deposit':
        wallet = instance.wallet
        wallet.balance += instance.amount
        wallet.save(update_fields=['balance'])

class BankAccount(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bank_accounts')
    account_holder_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)
    
    # Encrypted fields
    encrypted_account_number = models.TextField()
    encrypted_routing_number = models.TextField(blank=True, null=True)
    
    stripe_account_id = models.CharField(max_length=255, blank=True, null=True)

    # Metadata
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
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

class TokenPackage(models.Model):
    tokens = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False)
    color_gradient = models.CharField(max_length=100, help_text="Tailwind gradient classes, e.g., 'from-blue-500 to-cyan-500'")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.tokens} Tokens - ${self.price}"

    class Meta:
        verbose_name = 'Paquete de Tokens'
        verbose_name_plural = 'Paquetes de Tokens'
        ordering = ['tokens']

class GlobalSettings(models.Model):
    custom_token_price_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0.015,
        help_text="Precio en USD por cada token en recargas personalizadas."
    )
    view_rate_per_1000 = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default='0.1000',
        help_text="USD que se paga al creador por cada 1,000 vistas monetizables."
    )
    gift_fee_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=30.00,
        help_text="Porcentaje que se queda la plataforma de cada regalo (ej. 30 = 30%)."
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Configuración Global (Tokens: ${self.custom_token_price_usd})"

    class Meta:
        verbose_name = 'Configuración Global'
        verbose_name_plural = 'Configuraciones Globales'

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj

    def split_gift_tokens(self, token_price, fee_pct_override=None):
        """Reparte un regalo en (fee_plataforma, tokens_receptor) usando enteros.

        El receptor SIEMPRE recibe el resto exacto (total - fee), así la suma
        cuadra con cualquier porcentaje y nunca se crean ni se pierden tokens.
        El fee se redondea (half-up) para que la plataforma no pierda en impares.

        `fee_pct_override`: si se pasa (ej. la tarifa de un Early Creator Bonus),
        se usa en vez de la comisión global. Si es None, usa self.gift_fee_pct.

        Ej: 3 tokens al 50% → fee=2 (round 1.5), receptor=1, suma=3.
            5 tokens al 30% → fee=2 (round 1.5), receptor=3, suma=5.
        """
        from decimal import Decimal, ROUND_HALF_UP
        total = int(token_price)
        pct = Decimal(self.gift_fee_pct if fee_pct_override is None else fee_pct_override)
        fee = int((Decimal(total) * pct / Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        fee = max(0, min(fee, total))  # nunca negativo ni mayor al total
        receiver = total - fee
        return fee, receiver


class MonetizableViewLog(models.Model):
    """
    Registro de deduplicación: una fila por (user, video, date).
    Garantiza que un mismo usuario solo genera 1 vista monetizable por video por día,
    independientemente de cuántas veces el frontend envíe el evento.
    El backend inserta aquí antes de incrementar VideoStats.monetizable_views.
    """
    user    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='monetizable_view_logs')
    video   = models.ForeignKey('videos.Video', on_delete=models.CASCADE, related_name='monetizable_view_logs')
    date    = models.DateField()

    class Meta:
        unique_together = ('user', 'video', 'date')
        verbose_name = 'Monetizable View Log'
        verbose_name_plural = 'Monetizable View Logs'

    def __str__(self):
        return f"{self.user.username} → video {self.video_id} | {self.date}"


class VideoEarningsDaily(models.Model):
    """
    Snapshot diario de vistas monetizables nuevas por video.
    La task diaria calcula el delta (vistas nuevas del día) y lo guarda aquí.
    Al liquidar la semana se marca already_settled=True para nunca pagar dos veces.
    last_snapshot_total guarda el valor de monetizable_views en el momento del snapshot
    para que la task sea idempotente (si corre dos veces no dobla el delta).
    """
    video                = models.ForeignKey('videos.Video', on_delete=models.CASCADE, related_name='earnings_daily')
    creator              = models.ForeignKey(User, on_delete=models.CASCADE, related_name='video_earnings_daily')
    date                 = models.DateField()
    views_delta          = models.PositiveIntegerField(default=0)   # vistas monetizables nuevas ese día
    last_snapshot_total  = models.PositiveIntegerField(default=0)   # valor de monetizable_views al hacer snapshot
    already_settled      = models.BooleanField(default=False)       # True una vez que la semana fue liquidada

    class Meta:
        unique_together = ('video', 'date')
        verbose_name = 'Video Earnings Daily'
        verbose_name_plural = 'Video Earnings Daily'

    def __str__(self):
        return f"{self.creator.username} | video {self.video_id} | {self.date} | {self.views_delta} views"


class CreatorEarningsPeriod(models.Model):
    """
    Liquidación semanal por creador.
    Creada cada lunes por la Celery task, con status=pending hasta que
    el admin la apruebe — en ese momento se acredita al wallet del creador.
    """
    STATUS_CHOICES = [
        ('pending',    'Pendiente de aprobación'),
        ('processing', 'Procesando'),
        ('paid',       'Pagado'),
        ('rejected',   'Rechazado'),
    ]

    creator             = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earning_periods')
    week_start          = models.DateField()   # lunes
    week_end            = models.DateField()   # domingo
    monetizable_views   = models.PositiveIntegerField(default=0)   # total de la semana
    rate_per_1000       = models.DecimalField(max_digits=8, decimal_places=4)  # tarifa vigente al calcular
    gross_amount        = models.DecimalField(max_digits=10, decimal_places=4, default=0)  # views/1000 × rate
    platform_fee_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=0)   # reservado para futuro
    net_amount          = models.DecimalField(max_digits=10, decimal_places=4, default=0)  # lo que cobra el creador
    status              = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    paid_at             = models.DateTimeField(null=True, blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('creator', 'week_start')
        verbose_name = 'Creator Earnings Period'
        verbose_name_plural = 'Creator Earnings Periods'
        ordering = ['-week_start']

    def __str__(self):
        return f"{self.creator.username} | {self.week_start} → {self.week_end} | ${self.net_amount} | {self.status}"


class BonusCampaign(models.Model):
    """Campaña 'Early Creator': las primeras `capacity` personas que lleguen a
    `follower_threshold` seguidores ganan tarifas especiales por `duration_months`.
    Al llenarse el cupo, la campaña deja de aceptar nuevos ganadores."""
    name               = models.CharField(max_length=120)
    follower_threshold = models.PositiveIntegerField(help_text="N: seguidores requeridos para ganar.")
    capacity           = models.PositiveIntegerField(help_text="X: cupo de ganadores. Al llenarse, cierra.")
    duration_months    = models.PositiveIntegerField(default=3, help_text="D: meses que dura el bono por ganador.")
    gift_fee_pct       = models.DecimalField(
        max_digits=5, decimal_places=2, default=30.00,
        help_text="Comisión de regalos para los ganadores (reemplaza la global).")
    view_rate_per_1000 = models.DecimalField(
        max_digits=8, decimal_places=4, default='0.1000',
        help_text="USD por 1000 vistas para los ganadores (reemplaza la global).")
    is_active          = models.BooleanField(default=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Bonus Campaign'
        verbose_name_plural = 'Bonus Campaigns'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} (N={self.follower_threshold}, X={self.capacity})"

    @property
    def winners_count(self):
        return self.bonuses.count()

    @property
    def is_full(self):
        return self.bonuses.count() >= self.capacity


class CreatorBonusManager(models.Manager):
    def active_for(self, user):
        """Bono activo del usuario (expires_at > now), o None. Si hay varios,
        gana el de MAYOR view_rate_per_1000 (más favorable), desempate por el
        started_at más reciente. Gift-fee y view-rate salen de la misma fila."""
        return (self.get_queryset()
                .filter(user=user, expires_at__gt=timezone.now())
                .order_by('-view_rate_per_1000', '-started_at')
                .first())


class CreatorBonus(models.Model):
    """Un bono ganado por un usuario en una campaña. Las tarifas se snapshotean
    al ganar, así editar la campaña después NO altera a los ganadores existentes."""
    user                  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='creator_bonuses')
    campaign              = models.ForeignKey(BonusCampaign, on_delete=models.CASCADE, related_name='bonuses')
    started_at            = models.DateTimeField(default=timezone.now)
    expires_at            = models.DateTimeField()
    gift_fee_pct          = models.DecimalField(max_digits=5, decimal_places=2)
    view_rate_per_1000    = models.DecimalField(max_digits=8, decimal_places=4)
    follower_count_at_win = models.PositiveIntegerField(default=0)
    created_at            = models.DateTimeField(auto_now_add=True)

    objects = CreatorBonusManager()

    class Meta:
        unique_together = ('user', 'campaign')
        verbose_name = 'Creator Bonus'
        verbose_name_plural = 'Creator Bonuses'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'expires_at'])]

    def __str__(self):
        return f"{self.user.username} | {self.campaign.name} | expira {self.expires_at:%Y-%m-%d}"

    @property
    def is_active(self):
        return self.expires_at > timezone.now()

    @classmethod
    def active_for(cls, user):
        return cls.objects.active_for(user)
