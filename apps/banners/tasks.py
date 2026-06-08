import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='banners.sync_groups', max_retries=3, default_retry_delay=60)
def sync_groups_task(self, group_id=None):
    """
    Sincroniza membresías automáticas de grupos de banners.
    Corre cada hora desde CELERY_BEAT_SCHEDULE.
    También puede lanzarse manualmente con group_id para sincronizar un grupo específico.
    """
    try:
        from .sync import sync_all_groups
        added, removed = sync_all_groups(group_id=group_id)
        logger.info(f"[banners] sync_groups: +{added} added, -{removed} removed (group_id={group_id})")
        return {'added': added, 'removed': removed}
    except Exception as exc:
        logger.error(f"[banners] sync_groups failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@shared_task(name='banners.expire_banners')
def expire_banners_task():
    """
    Desactiva banners cuya fecha de expiración ya pasó.
    Corre cada 15 minutos.
    """
    from .models import BuzzyBanner
    now = timezone.now()
    expired = BuzzyBanner.objects.filter(
        is_active=True,
        expires_at__isnull=False,
        expires_at__lte=now,
    )
    count = expired.count()
    expired.update(is_active=False)
    logger.info(f"[banners] expire_banners: {count} banners desactivados")
    return {'expired': count}


@shared_task(name='banners.cleanup_old_views')
def cleanup_old_views_task():
    """
    Elimina registros BannerView de banners ya inactivos (limpieza mensual).
    """
    from .models import BannerView, BuzzyBanner
    inactive_ids = BuzzyBanner.objects.filter(is_active=False).values_list('id', flat=True)
    deleted, _ = BannerView.objects.filter(banner_id__in=inactive_ids).delete()
    logger.info(f"[banners] cleanup_old_views: {deleted} registros eliminados")
    return {'deleted': deleted}
