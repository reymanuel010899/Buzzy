from django.db import models
from django.utils import timezone
from apps.users.models import User


class UserGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_auto = models.BooleanField(default=True, help_text="Si es True, se sincroniza automáticamente por requisitos")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Grupo de usuarios"
        verbose_name_plural = "Grupos de usuarios"


class GroupRequirement(models.Model):
    FIELD_CHOICES = [
        ('has_subscription', 'Tiene suscripción activa'),
        ('subscription_plan', 'Plan de suscripción'),
        ('followers_count', 'Cantidad de seguidores'),
        ('following_count', 'Cantidad de seguidos'),
        ('account_age_days', 'Días desde registro'),
        ('total_videos', 'Videos publicados'),
        ('is_buzzy_premium', 'Tiene Buzzy Premium'),
        ('country', 'País'),
        ('total_tokens', 'Tokens en wallet'),
        ('videos_this_month', 'Videos este mes'),
    ]

    OPERATOR_CHOICES = [
        ('eq', 'Igual a'),
        ('gt', 'Mayor que'),
        ('lt', 'Menor que'),
        ('gte', 'Mayor o igual'),
        ('lte', 'Menor o igual'),
        ('in', 'Está en lista (separar por comas)'),
    ]

    group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name='requirements')
    field = models.CharField(max_length=50, choices=FIELD_CHOICES)
    operator = models.CharField(max_length=10, choices=OPERATOR_CHOICES)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.group.name} — {self.field} {self.operator} {self.value}"

    class Meta:
        verbose_name = "Requisito de grupo"
        verbose_name_plural = "Requisitos de grupo"


class UserGroupMembership(models.Model):
    ADDED_BY_CHOICES = [('AUTO', 'Automático'), ('MANUAL', 'Manual')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_memberships')
    group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name='memberships')
    joined_at = models.DateTimeField(auto_now_add=True)
    added_by = models.CharField(max_length=10, choices=ADDED_BY_CHOICES, default='AUTO')

    class Meta:
        unique_together = ('user', 'group')
        verbose_name = "Membresía de grupo"
        verbose_name_plural = "Membresías de grupo"

    def __str__(self):
        return f"{self.user.username} → {self.group.name} ({self.added_by})"


class BuzzyBanner(models.Model):
    TYPE_CHOICES = [
        ('ANNOUNCEMENT', 'Anuncio'),
        ('ALERT', 'Alerta'),
        ('ACHIEVEMENT', 'Logro'),
        ('PRIZE', 'Premio'),
        ('OFFER', 'Oferta'),
    ]

    EFFECT_CHOICES = [
        ('PARTICLES', 'Partículas'),
        ('HOLOGRAPHIC', 'Holográfico'),
        ('SCRATCH', 'Rasca y Revela'),
        ('NARRATIVE', 'Narrativo'),
        ('COUNTDOWN', 'Cuenta Regresiva'),
        ('NONE', 'Sin efecto'),
    ]

    TARGET_CHOICES = [
        ('GLOBAL', 'Global — todos los usuarios'),
        ('PERSONAL', 'Personal — un usuario'),
        ('GROUP', 'Grupo — grupo de usuarios'),
    ]

    # Contenido
    title = models.CharField(max_length=150)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='ANNOUNCEMENT')
    effect = models.CharField(max_length=20, choices=EFFECT_CHOICES, default='NONE')

    # Destino
    target = models.CharField(max_length=10, choices=TARGET_CHOICES, default='GLOBAL')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='personal_banners')
    group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, null=True, blank=True, related_name='banners')

    # Estilo
    background_color = models.CharField(max_length=50, default='#7C3AED')
    text_color = models.CharField(max_length=50, default='#FFFFFF')
    accent_color = models.CharField(max_length=50, default='#A78BFA')

    # Extras según efecto
    reveal_content = models.TextField(blank=True, help_text="Texto que se revela al rascar (SCRATCH)")
    countdown_label = models.CharField(max_length=100, blank=True, help_text="Label del contador (COUNTDOWN)")

    # Media e interacción
    image = models.ImageField(upload_to='banners/', null=True, blank=True, help_text="Imagen decorativa opcional")
    action_url = models.CharField(max_length=500, blank=True, help_text="Ruta interna de la app ej: /wallet, /profile/123")
    action_label = models.CharField(max_length=80, blank=True, help_text="Texto del botón CTA ej: Ver oferta")

    # Control
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    priority = models.PositiveSmallIntegerField(default=0, help_text="Mayor número = mayor prioridad dentro del mismo target")

    def is_expired(self):
        if self.expires_at and timezone.now() > self.expires_at:
            return True
        return False

    def __str__(self):
        return f"[{self.type}] {self.title} → {self.target}"

    class Meta:
        verbose_name = "Banner Buzzy"
        verbose_name_plural = "Banners Buzzy"
        ordering = ['-priority', '-created_at']


class BannerView(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='banner_views')
    banner = models.ForeignKey(BuzzyBanner, on_delete=models.CASCADE, related_name='views')
    seen_at = models.DateTimeField(auto_now_add=True)
    dismissed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'banner')
        verbose_name = "Vista de banner"
        verbose_name_plural = "Vistas de banner"

    def __str__(self):
        return f"{self.user.username} vio '{self.banner.title}'"


class BannerInteraction(models.Model):
    ACTION_CHOICES = [
        ('view',    'Vista'),
        ('click',   'Click en CTA'),
        ('dismiss', 'Descartado'),
        ('scratch', 'Rascado completo'),
        ('expired', 'Expiró automáticamente'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='banner_interactions')
    banner = models.ForeignKey(BuzzyBanner, on_delete=models.CASCADE, related_name='interactions')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Interacción de banner"
        verbose_name_plural = "Interacciones de banner"
        indexes = [
            models.Index(fields=['banner', 'action']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} → {self.action} en '{self.banner.title}'"
