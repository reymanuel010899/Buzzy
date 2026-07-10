"""Servicios del wallet relacionados con los Early Creator Bonus."""
import logging

from django.db import transaction, IntegrityError
from django.utils import timezone
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


def try_enroll_creator_bonuses(user):
    """Inscribe a `user` en toda BonusCampaign activa, no llena y cuyo umbral de
    seguidores ya cumple. Idempotente y a prueba de carreras. NUNCA lanza: ante
    cualquier error lo registra y sigue, para no romper la acción de seguir.

    Devuelve la lista de CreatorBonus creados (para tests/logging).
    """
    from apps.wallet.models import BonusCampaign, CreatorBonus

    created = []
    try:
        follower_count = user.followers.count()

        # Campañas candidatas: activas, umbral cumplido y donde aún no ganó.
        candidate_ids = list(
            BonusCampaign.objects
            .filter(is_active=True, follower_threshold__lte=follower_count)
            .exclude(bonuses__user=user)
            .values_list('id', flat=True)
        )

        for cid in candidate_ids:
            try:
                with transaction.atomic():
                    # Lock de la fila de campaña: serializa la decisión de cupo.
                    campaign = (BonusCampaign.objects
                                .select_for_update()
                                .get(id=cid, is_active=True))

                    # Re-chequeo de capacidad DENTRO del lock (autoritativo).
                    if campaign.bonuses.count() >= campaign.capacity:
                        continue
                    # Defensivo: ya inscrito (respaldado por unique_together).
                    if campaign.bonuses.filter(user=user).exists():
                        continue

                    now = timezone.now()
                    bonus = CreatorBonus.objects.create(
                        user=user,
                        campaign=campaign,
                        started_at=now,
                        expires_at=now + relativedelta(months=campaign.duration_months),
                        gift_fee_pct=campaign.gift_fee_pct,
                        view_rate_per_1000=campaign.view_rate_per_1000,
                        follower_count_at_win=follower_count,
                    )
                    created.append(bonus)
            except IntegrityError:
                # Carrera en unique_together: otra request ya lo inscribió. OK.
                continue
            except Exception:
                logger.exception("[bonus] enroll falló user=%s campaign=%s", user.id, cid)
                continue

        # Notificar al ganador (fuera de la transacción; nunca debe romper nada).
        for bonus in created:
            try:
                from apps.videos.views import notify_system
                from apps.videos.models import Notification
                meses = bonus.campaign.duration_months
                notify_system(
                    recipient=user,
                    message=(f"🎉 ¡Felicidades! Ganaste el bono '{bonus.campaign.name}'. "
                             f"Tarifas especiales en regalos y vistas por {meses} "
                             f"{'mes' if meses == 1 else 'meses'}."),
                    notification_type=Notification.Type.EARNING,
                )
            except Exception:
                logger.exception("[bonus] notify falló user=%s bonus=%s", user.id, bonus.id)
    except Exception:
        logger.exception("[bonus] try_enroll_creator_bonuses error user=%s",
                         getattr(user, 'id', None))
    return created
