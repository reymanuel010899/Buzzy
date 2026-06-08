import secrets
from datetime import timedelta
from django.db import models
from django.utils import timezone
from apps.users.models import User


def _default_expires_at():
    return timezone.now() + timedelta(days=30)


def _generate_token():
    return secrets.token_urlsafe(32)


class ReferralToken(models.Model):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='referral_tokens',
        verbose_name='Dueño del link',
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_token,
        verbose_name='Token único',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Activo',
        db_index=True,
    )
    used_by = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='used_referral_token',
        verbose_name='Usado por',
    )
    expires_at = models.DateTimeField(
        default=_default_expires_at,
        verbose_name='Expira en',
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Token de Referido'
        verbose_name_plural = 'Tokens de Referidos'
        indexes = [
            models.Index(fields=['token', 'is_active']),
        ]

    def __str__(self):
        return f"{self.owner.username} → {self.token[:12]}... | activo={self.is_active}"

    @property
    def is_valid(self):
        return self.is_active and timezone.now() < self.expires_at


class ReferralProfile(models.Model):
    """
    Contador histórico de referidos exitosos por usuario.
    Se crea automáticamente al registrarse (via signal).
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='referral_profile',
    )
    total_invitados = models.PositiveIntegerField(
        default=0,
        verbose_name='Total de invitados exitosos',
    )

    class Meta:
        verbose_name = 'Perfil de Referido'
        verbose_name_plural = 'Perfiles de Referidos'

    def __str__(self):
        return f"{self.user.username} — {self.total_invitados} invitados"
