from celery import shared_task
from django.utils import timezone


@shared_task(name='referrals.delete_expired_tokens')
def delete_expired_tokens():
    """
    Elimina tokens de referido no usados que ya pasaron su ventana de 24h.
    Corre cada hora via Celery Beat.
    """
    from .models import ReferralToken

    deleted_count, _ = ReferralToken.objects.filter(
        is_active=True,
        expires_at__lt=timezone.now(),
    ).delete()

    return f"Tokens expirados eliminados: {deleted_count}"
