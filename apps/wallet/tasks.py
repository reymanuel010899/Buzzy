from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from decimal import Decimal
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@shared_task(name="wallet.snapshot_monetizable_views")
def snapshot_monetizable_views():
    """
    Corre cada noche a las 23:50.

    Por cada video, calcula cuántas vistas monetizables NUEVAS hubo desde el
    último snapshot y guarda el delta en VideoEarningsDaily.

    Idempotente: usa last_snapshot_total para saber desde dónde contar.
    Si la task corre dos veces el mismo día, el segundo run detecta que
    current_total == last_snapshot_total y produce delta=0, sin doblar.

    El contador VideoStats.monetizable_views NUNCA se resetea — es acumulado
    de por vida del video. El delta diario es lo que se liquida cada semana.
    Al liquidar, already_settled=True protege contra doble pago.
    """
    from apps.videos.models import VideoStats
    from apps.wallet.models import VideoEarningsDaily

    today = timezone.now().date()
    created_count = 0
    updated_count = 0

    for stats in VideoStats.objects.select_related('video', 'video__user_id').iterator():
        video = stats.video
        creator = video.user_id
        current_total = stats.monetizable_views

        if current_total == 0:
            continue

        # Obtener o crear el registro del día
        record, created = VideoEarningsDaily.objects.get_or_create(
            video=video,
            date=today,
            defaults={
                'creator': creator,
                'views_delta': 0,
                'last_snapshot_total': current_total,
                'already_settled': False,
            }
        )

        if created:
            # Primer run del día: delta = total actual - total al final de ayer
            # "total al final de ayer" = suma de todos los deltas anteriores ya guardados
            from django.db.models import Sum
            previous_total = VideoEarningsDaily.objects.filter(
                video=video,
                date__lt=today,
            ).aggregate(s=Sum('views_delta'))['s'] or 0

            delta = current_total - previous_total
            if delta > 0:
                VideoEarningsDaily.objects.filter(pk=record.pk).update(
                    views_delta=delta,
                    last_snapshot_total=current_total,
                )
            created_count += 1
        else:
            # Ya existe el registro de hoy — solo actualizar si hay vistas nuevas
            # desde el último snapshot (idempotente: last_snapshot_total lo marca)
            if current_total <= record.last_snapshot_total:
                continue

            new_delta = current_total - record.last_snapshot_total
            VideoEarningsDaily.objects.filter(pk=record.pk).update(
                views_delta=F('views_delta') + new_delta,
                last_snapshot_total=current_total,
            )
            updated_count += 1

    logger.info(f"[snapshot_monetizable_views] {today} — creados: {created_count}, actualizados: {updated_count}")
    return {'date': str(today), 'created': created_count, 'updated': updated_count}


@shared_task(name="wallet.settle_weekly_earnings")
def settle_weekly_earnings():
    """
    Corre cada lunes a las 02:00 AM.

    Liquida la semana anterior (lunes–domingo):
    1. Suma los deltas diarios no liquidados de esa semana por creador.
    2. Única condición: mínimo 1,000 vistas monetizables en la semana.
       Sin mínimo de monto — cualquier valor ($0.10, $0.25, etc.) se acredita.
       El creador ve sus ganancias desde la primera semana, sin importar cuánto sean.
    3. Crea CreatorEarningsPeriod con status='pending'.
    4. Marca los VideoEarningsDaily como already_settled=True.

    Las vistas de semanas anteriores ya liquidadas están marcadas
    already_settled=True y nunca se vuelven a contar.
    El contador acumulado VideoStats.monetizable_views NO se toca —
    el delta diario es la única fuente de verdad para pagos.
    """
    from apps.wallet.models import VideoEarningsDaily, CreatorEarningsPeriod, GlobalSettings, CreatorBonus
    from django.db.models import Sum
    from django.contrib.auth import get_user_model

    User = get_user_model()
    cfg = GlobalSettings.get_settings()
    rate = cfg.view_rate_per_1000  # Decimal

    today = timezone.now().date()
    # Semana anterior: lunes → domingo
    week_end   = today - timedelta(days=today.weekday() + 1)   # domingo pasado
    week_start = week_end - timedelta(days=6)                   # lunes pasado

    # Solo se requiere el mínimo de vistas — cualquier monto se acredita al wallet.
    # El creador ve sus centavos desde la primera semana, lo que motiva a seguir publicando.
    MIN_VIEWS = 1000

    daily_qs = (
        VideoEarningsDaily.objects
        .filter(date__gte=week_start, date__lte=week_end, already_settled=False)
        .values('creator')
        .annotate(total_views=Sum('views_delta'))
    )

    periods_created = 0

    for row in daily_qs:
        total_views = row['total_views'] or 0
        if total_views < MIN_VIEWS:
            continue

        creator = User.objects.get(pk=row['creator'])

        # Early Creator Bonus: la tarifa del bono solo aplica a las vistas
        # GENERADAS DESPUÉS de ganar el bono (date >= started_at). Las vistas
        # previas de la misma semana se pagan a la tarifa global. Por eso se
        # separan en dos tramos por fecha en vez de aplicar una tarifa a todo.
        _bonus = CreatorBonus.active_for(creator)
        if _bonus:
            # Inicio del tramo con tarifa de bono: el más tardío entre el inicio
            # de la semana y la fecha en que ganó el bono.
            bonus_from = max(week_start, _bonus.started_at.date())
            views_after = (
                VideoEarningsDaily.objects
                .filter(creator=creator, date__gte=bonus_from, date__lte=week_end,
                        already_settled=False)
                .aggregate(s=Sum('views_delta'))['s'] or 0
            )
            views_before = total_views - views_after
            gross = (
                Decimal(views_before) / Decimal('1000') * rate +
                Decimal(views_after) / Decimal('1000') * _bonus.view_rate_per_1000
            )
            # Tarifa "representativa" guardada en el period: la efectiva promedio.
            effective_rate = (gross / Decimal(total_views) * Decimal('1000')) if total_views else rate
        else:
            effective_rate = rate
            gross = Decimal(total_views) / Decimal('1000') * rate

        net = gross  # platform_fee_pct = 0 por ahora

        with transaction.atomic():
            period, created = CreatorEarningsPeriod.objects.get_or_create(
                creator=creator,
                week_start=week_start,
                defaults={
                    'week_end': week_end,
                    'monetizable_views': total_views,
                    'rate_per_1000': effective_rate,
                    'gross_amount': gross,
                    'platform_fee_pct': Decimal('0'),
                    'net_amount': net,
                    'status': 'pending',
                }
            )

            if created:
                # Marcar los registros diarios como liquidados — nunca se pagarán de nuevo
                VideoEarningsDaily.objects.filter(
                    creator=creator,
                    date__gte=week_start,
                    date__lte=week_end,
                    already_settled=False
                ).update(already_settled=True)

                periods_created += 1
                logger.info(
                    f"[settle_weekly_earnings] {creator.username} | "
                    f"{total_views:,} vistas | ${net} USD | {week_start}→{week_end}"
                )

    logger.info(f"[settle_weekly_earnings] Periodos creados: {periods_created} | semana {week_start}→{week_end}")
    return {'week_start': str(week_start), 'week_end': str(week_end), 'periods_created': periods_created}


@shared_task(name="wallet.approve_earning_period")
def approve_earning_period(period_id: int):
    """
    Se llama desde el admin al aprobar un CreatorEarningsPeriod.
    Acredita el net_amount al wallet del creador y cambia status → paid.

    Protección contra doble pago:
    - select_for_update() en el periodo bloquea la fila antes de cualquier cambio.
    - El check status != 'pending' dentro del atomic bloque un segundo intento.
    - Todo ocurre en una sola transacción atómica: si falla a mitad, revierte.
    """
    from apps.wallet.models import CreatorEarningsPeriod, WalletModel, TransactionModel

    try:
        with transaction.atomic():
            # Bloquear la fila del periodo para evitar ejecución concurrente
            period = (
                CreatorEarningsPeriod.objects
                .select_for_update()
                .select_related('creator')
                .get(pk=period_id)
            )

            if period.status != 'pending':
                logger.warning(
                    f"[approve_earning_period] Period {period_id} ya procesado ({period.status}). Ignorando."
                )
                return {'skipped': True, 'status': period.status}

            # Cambiar a processing primero para que un retry no entre aquí de nuevo
            period.status = 'processing'
            period.save(update_fields=['status'])

            wallet = WalletModel.objects.select_for_update().get(
                user=period.creator, wallet_type='main'
            )
            wallet.balance = F('balance') + period.net_amount
            wallet.save(update_fields=['balance'])

            TransactionModel.objects.create(
                wallet=wallet,
                transaction_type='deposit',
                status='completed',
                amount=period.net_amount,
                description=(
                    f"Ganancias por vistas — semana {period.week_start} al {period.week_end} "
                    f"({period.monetizable_views:,} vistas)"
                )
            )

            period.status = 'paid'
            period.paid_at = timezone.now()
            period.save(update_fields=['status', 'paid_at'])

    except CreatorEarningsPeriod.DoesNotExist:
        logger.error(f"[approve_earning_period] Period {period_id} no encontrado.")
        return

    # Notificación en la app + WebSocket
    _notify_earning(period)

    logger.info(f"[approve_earning_period] Pagado: {period.creator.username} | ${period.net_amount} USD")
    return {'period_id': period_id, 'paid': str(period.net_amount)}


def _notify_earning(period):
    """Crea la notificación de pago y la transmite por WebSocket al creador."""
    import requests as req
    from django.conf import settings as django_settings
    from apps.videos.models import Notification

    amount = period.net_amount.normalize()
    message = f"Buzzy te depositó ${amount} por tus vistas de la semana {period.week_start.strftime('%d %b')} al {period.week_end.strftime('%d %b')}"

    notif = Notification.objects.create(
        recipient=period.creator,
        actor=None,
        notification_type=Notification.Type.EARNING,
        message=message,
    )

    payload = {
        "recipient_id": period.creator.id,
        "event": "notification",
        "id": notif.id,
        "notification_type": Notification.Type.EARNING,
        "message": message,
        "actor": None,
        "video_uuid": None,
        "video_thumbnail": None,
        "created_at": notif.created_at.isoformat(),
        "is_read": False,
    }

    try:
        req.post(
            f"{django_settings.FASTAPI_WS_URL}/broadcast-notification/",
            json=payload,
            timeout=2,
        )
    except Exception as e:
        logger.warning(f"[approve_earning_period] WS notification failed: {e}")
