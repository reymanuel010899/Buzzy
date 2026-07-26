from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from .manayers import CustomUserManager
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, check_password
from django.db.models.signals import post_save
from django.dispatch import receiver
from Buzzy.encrypted_fields import EncryptedTextField
# Create your models here.

class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)

    def __str__(self):
        return self.name
    
class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    birthdate = models.DateField(null=True, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/photo/', default='profile_pics/avatar.webp', null=True, blank=True)
    profile_video = models.FileField(upload_to='profile_videos/video/', null=True, blank=True)
    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True, unique=True)
    is_phone_verified = models.BooleanField(default=False)
    sms_attempts = models.PositiveSmallIntegerField(default=0)
    sms_blocked_until = models.DateTimeField(null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    # Language preference
    LANGUAGE_CHOICES = [('en', 'English'), ('es', 'Español')]
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='en')

    # Recovery codes
    reset_password_code = models.CharField(max_length=6, null=True, blank=True)
    reset_password_expires = models.DateTimeField(null=True, blank=True)

    # IP de registro — para limitar 5 cuentas por IP
    registration_ip = models.GenericIPAddressField(null=True, blank=True)

    is_owner = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)

    # Preferencias de SONIDO de notificación por categoría. La notificación visual
    # siempre llega; estos toggles solo controlan si el push suena. True = suena.
    notif_sound_messages  = models.BooleanField(default=True)
    notif_sound_gifts     = models.BooleanField(default=True)
    notif_sound_followers = models.BooleanField(default=True)

    # Referral pendiente: se guarda al registro y se procesa solo cuando el teléfono es verificado con Firebase
    pending_referral_code = models.CharField(max_length=64, null=True, blank=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.username

    def all_followers(self):
        return self.followers.order_by('user_id').distinct('user_id')

    def all_followed(self):
        return self.following.order_by('follower_user_id').distinct('follower_user_id')

    def total_social_followers(self):
        return sum(account.followers_count for account in self.social_accounts.all())

    def all_likes(self):
        return sum(like.like_video_reverce.count() for like in self.user_reverce.all())

    def all_comments(self):
        return sum(comment.comernt_video_reverce.count() for comment in self.user_reverce.all())

    def all_views(self):
        return sum(video.video_reverce.count() for video in self.user_reverce.all())

    def is_currently_available(self):
        now = timezone.localtime()
        current_day = now.weekday()
        current_time = now.time().replace(tzinfo=None, microsecond=0)
        return self.availabilities.filter(
            day_of_week=current_day,
            is_active=True,
            start_time__lte=current_time,
            end_time__gte=current_time
        ).exists()


class FCMDevice(models.Model):
    """Guarda los tokens FCM de los dispositivos móviles de cada usuario."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="fcm_devices")
    token = models.TextField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user"])]

    def __str__(self):
        return f"{self.user.username} — {self.token[:20]}..."

class BuzzyPremium(models.Model):
    """Platform-level Premium subscription (Buzzy Premium, $5.99/mo)."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='buzzy_premium')
    stripe_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Buzzy Premium'
        verbose_name_plural = 'Buzzy Premiums'

    def __str__(self):
        return f"{self.user.username} — Premium ({self.status})"

    @property
    def is_active(self):
        from django.utils import timezone
        if self.status != 'active':
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True


class Trending(models.Model):
    term = models.CharField(max_length=255, unique=True)
    count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.term

    class Meta:
        verbose_name = 'Trending'
        verbose_name_plural = 'Trending'
        ordering = ['-count', '-updated_at']

class RecentSearch(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recent_searches')
    term = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} searched for {self.term}"

    class Meta:
        verbose_name = 'Recent Search'
        verbose_name_plural = 'Recent Searches'
        ordering = ['-created_at']
        unique_together = ('user', 'term')

class Availability(models.Model):
    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='availabilities'
    )
    
    day_of_week = models.PositiveSmallIntegerField(choices=DAYS_OF_WEEK)
    
    start_time = models.TimeField()
    end_time = models.TimeField()
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['user', 'day_of_week', 'start_time', 'end_time']
        verbose_name_plural = "Availabilities"

    def clean(self):
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValidationError("La hora de fin debe ser posterior a la de inicio.")

    def __str__(self):
        return f"{self.user.username} - {self.get_day_of_week_display()} ({self.start_time} - {self.end_time})"


class SocialAccount(models.Model):
    PLATFORM_CHOICES = [
        ('instagram', 'Instagram'),
        ('tiktok', 'TikTok'),
        ('facebook', 'Facebook'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='social_accounts'
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    platform_user_id = models.CharField(max_length=255)
    platform_username = models.CharField(max_length=255, blank=True)
    # Tokens OAuth cifrados en reposo (Fernet) vía EncryptedTextField. El código
    # los lee/escribe como texto normal; en la BD quedan cifrados con prefijo enc::
    access_token = EncryptedTextField()
    refresh_token = EncryptedTextField(blank=True)
    followers_count = models.PositiveIntegerField(default=0)
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'platform')
        verbose_name = 'Social Account'
        verbose_name_plural = 'Social Accounts'

    def __str__(self):
        return f"{self.user.username} → {self.platform} (@{self.platform_username})"


class UserSecurity(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='security')
    chat_pin_hash = models.CharField(max_length=255, blank=True, default='')
    hidden_pin_verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Security'
        verbose_name_plural = 'User Security'

    def __str__(self):
        return f"{self.user.username} security"

    @property
    def has_chat_pin(self) -> bool:
        return bool(self.chat_pin_hash)

    def set_chat_pin(self, pin: str) -> None:
        self.chat_pin_hash = make_password(pin)
        self.hidden_pin_verified_at = None
        self.save(update_fields=['chat_pin_hash', 'hidden_pin_verified_at', 'updated_at'])

    def clear_chat_pin(self) -> None:
        self.chat_pin_hash = ''
        self.hidden_pin_verified_at = None
        self.save(update_fields=['chat_pin_hash', 'hidden_pin_verified_at', 'updated_at'])

    def verify_chat_pin(self, pin: str) -> bool:
        if not self.chat_pin_hash:
            return False
        return check_password(pin, self.chat_pin_hash)

    def mark_hidden_verified(self) -> None:
        self.hidden_pin_verified_at = timezone.now()
        self.save(update_fields=['hidden_pin_verified_at', 'updated_at'])

    def hidden_access_is_fresh(self, minutes: int = 5) -> bool:
        if not self.hidden_pin_verified_at:
            return False
        return timezone.now() - self.hidden_pin_verified_at <= timedelta(minutes=minutes)


@receiver(post_save, sender=User)
def ensure_user_security(sender, instance, created, **kwargs):
    if created:
        UserSecurity.objects.get_or_create(user=instance)
