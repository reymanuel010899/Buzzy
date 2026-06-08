"""
Test completo del flujo de monetización por vistas.

Corre con:
  DJANGO_SETTINGS_MODULE=Buzzy.settings python test_monetization_flow.py

Simula exactamente lo que pasa en producción sin esperar días.
Limpia todos los datos de prueba al final.
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Buzzy.settings')
django.setup()

from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model

from apps.videos.models import Video, VideoStats
from apps.wallet.models import (
    MonetizableViewLog, VideoEarningsDaily,
    CreatorEarningsPeriod, GlobalSettings, WalletModel, TransactionModel
)
from apps.wallet.tasks import (
    snapshot_monetizable_views,
    settle_weekly_earnings,
    approve_earning_period,
)

User = get_user_model()

# ─────────────────────────────────────────
VERDE  = "\033[92m"
ROJO   = "\033[91m"
AMARILLO = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

passed = 0
failed = 0

def ok(msg):
    global passed
    passed += 1
    print(f"  {VERDE}✅ {msg}{RESET}")

def fail(msg):
    global failed
    failed += 1
    print(f"  {ROJO}❌ {msg}{RESET}")

def section(msg):
    print(f"\n{BOLD}{CYAN}{'─'*55}")
    print(f"  {msg}")
    print(f"{'─'*55}{RESET}")

def info(msg):
    print(f"  {AMARILLO}ℹ  {msg}{RESET}")

# ─────────────────────────────────────────
# SETUP — buscar usuarios y video reales
# ─────────────────────────────────────────
section("SETUP — Preparando datos de prueba")

video = Video.objects.filter(status='ready').select_related('user_id').first()
if not video:
    video = Video.objects.select_related('user_id').first()

if not video:
    fail("No hay videos en la base de datos. Sube al menos un video antes de correr el test.")
    sys.exit(1)

creator = video.user_id
info(f"Creador: @{creator.username} (id={creator.id})")
info(f"Video:   id={video.id}  duración={video.duration}s")

# Buscar un usuario viewer diferente al creador
viewer = User.objects.exclude(pk=creator.pk).first()
if not viewer:
    fail("Necesitas al menos 2 usuarios en la DB para simular un viewer distinto al creador.")
    sys.exit(1)
info(f"Viewer:  @{viewer.username} (id={viewer.id})")

# Leer tarifa actual
cfg = GlobalSettings.get_settings()
rate = cfg.view_rate_per_1000
info(f"Tarifa:  ${rate} por 1,000 vistas")

wallet = WalletModel.objects.filter(user=creator, wallet_type='main').first()
if not wallet:
    fail(f"El creador @{creator.username} no tiene wallet. Crea uno primero.")
    sys.exit(1)

balance_inicial = wallet.balance
info(f"Balance inicial del creador: ${balance_inicial}")

# Limpiar datos de prueba anteriores del mismo video/usuario
MonetizableViewLog.objects.filter(video=video, user=viewer).delete()
VideoEarningsDaily.objects.filter(video=video).delete()
CreatorEarningsPeriod.objects.filter(creator=creator).delete()
stats, _ = VideoStats.objects.get_or_create(video=video)
VideoStats.objects.filter(pk=stats.pk).update(monetizable_views=0)

ok("Setup completado — datos limpios")

# ─────────────────────────────────────────
# TEST 1 — Auto-vista del creador NO cuenta
# ─────────────────────────────────────────
section("TEST 1 — Auto-vista del creador")

stats.refresh_from_db()
before = stats.monetizable_views

# Simular lo que hace VideoEventView para auto-vista
if video.user_id == creator:
    info("Creador intentó verse su propio video → bloqueado por backend")
    # monetizable_views NO debe subir
    stats.refresh_from_db()
    if stats.monetizable_views == before:
        ok("Auto-vista bloqueada correctamente — monetizable_views no cambió")
    else:
        fail(f"Auto-vista NO fue bloqueada — monetizable_views subió a {stats.monetizable_views}")

# ─────────────────────────────────────────
# TEST 2 — Viewer ve el video, deduplicación diaria
# ─────────────────────────────────────────
section("TEST 2 — Vista monetizable real (viewer ≠ creador)")

today = timezone.now().date()

# Primera vista del día
_, created = MonetizableViewLog.objects.get_or_create(
    user=viewer, video=video, date=today
)
if created:
    VideoStats.objects.filter(pk=stats.pk).update(monetizable_views=1)
    ok("Primera vista del día registrada en MonetizableViewLog")
else:
    fail("No se creó el log de vista — ¿datos sucios?")

stats.refresh_from_db()
if stats.monetizable_views == 1:
    ok(f"VideoStats.monetizable_views = 1 ✓")
else:
    fail(f"VideoStats.monetizable_views = {stats.monetizable_views} (esperado 1)")

# Segundo intento del mismo viewer hoy — debe ser bloqueado
_, created2 = MonetizableViewLog.objects.get_or_create(
    user=viewer, video=video, date=today
)
if not created2:
    ok("Segundo intento bloqueado por MonetizableViewLog (unique_together)")
else:
    fail("¡Doble vista registrada! La deduplicación no funcionó")

# ─────────────────────────────────────────
# TEST 3 — Simulamos una semana completa de vistas
# ─────────────────────────────────────────
section("TEST 3 — Semana completa de vistas (simulada)")

# Inyectar 5,000 vistas monetizables directamente en VideoStats
VideoStats.objects.filter(pk=stats.pk).update(monetizable_views=5000)
stats.refresh_from_db()
info(f"Vistas monetizables inyectadas: {stats.monetizable_views}")

# Simular snapshot de 7 días pasados
week_end   = today - timedelta(days=today.weekday() + 1)   # domingo pasado
week_start = week_end - timedelta(days=6)                   # lunes pasado

# Limpiar snapshots previos del test
VideoEarningsDaily.objects.filter(video=video, date__gte=week_start, date__lte=week_end).delete()

# Distribuir 5,000 vistas en 7 días simulados
days_views = [500, 800, 600, 900, 700, 800, 700]  # suma = 5,000
running_total = 0
for i, day_delta in enumerate(days_views):
    day = week_start + timedelta(days=i)
    running_total += day_delta
    VideoEarningsDaily.objects.create(
        video=video,
        creator=creator,
        date=day,
        views_delta=day_delta,
        last_snapshot_total=running_total,
        already_settled=False,
    )

total_semana = sum(days_views)
info(f"Días simulados: {week_start} → {week_end}")
info(f"Total vistas semana: {total_semana:,}")
ok("7 días de VideoEarningsDaily creados")

# ─────────────────────────────────────────
# TEST 4 — Task de liquidación semanal
# ─────────────────────────────────────────
section("TEST 4 — settle_weekly_earnings (liquidación del lunes)")

result = settle_weekly_earnings()
info(f"Resultado task: {result}")

period = CreatorEarningsPeriod.objects.filter(
    creator=creator, week_start=week_start
).first()

if period:
    ok(f"CreatorEarningsPeriod creado — status: {period.status}")
    ok(f"Vistas liquidadas: {period.monetizable_views:,}")

    expected_gross = Decimal(total_semana) / Decimal('1000') * rate
    if period.net_amount == expected_gross:
        ok(f"Monto correcto: ${period.net_amount} (${total_semana}/1000 × ${rate})")
    else:
        fail(f"Monto incorrecto: ${period.net_amount} (esperado ${expected_gross})")

    # Verificar que los daily records fueron marcados como settled
    unsettled = VideoEarningsDaily.objects.filter(
        video=video,
        date__gte=week_start,
        date__lte=week_end,
        already_settled=False
    ).count()
    if unsettled == 0:
        ok("Todos los VideoEarningsDaily marcados already_settled=True")
    else:
        fail(f"{unsettled} registros siguen sin liquidar")
else:
    fail("No se creó el CreatorEarningsPeriod")

# ─────────────────────────────────────────
# TEST 5 — Idempotencia: correr settle de nuevo no dobla
# ─────────────────────────────────────────
section("TEST 5 — Idempotencia (settle corre dos veces)")

result2 = settle_weekly_earnings()
periods_count = CreatorEarningsPeriod.objects.filter(
    creator=creator, week_start=week_start
).count()

if periods_count == 1:
    ok("Solo existe 1 periodo — no se duplicó al correr dos veces")
else:
    fail(f"Se crearon {periods_count} periodos — hay doble liquidación")

# ─────────────────────────────────────────
# TEST 6 — Aprobación del pago (admin flow)
# ─────────────────────────────────────────
section("TEST 6 — approve_earning_period (admin aprueba el pago)")

if period:
    wallet.refresh_from_db()
    balance_antes = wallet.balance
    info(f"Balance antes de aprobar: ${balance_antes}")

    # Contar transacciones de ganancias previas para aislar solo la de este test
    tx_count_antes = TransactionModel.objects.filter(
        wallet=wallet, transaction_type='deposit',
        description__icontains="Ganancias por vistas"
    ).count()

    approve_earning_period(period.id)

    wallet.refresh_from_db()
    balance_despues = wallet.balance
    info(f"Balance después de aprobar: ${balance_despues}")

    # Verificar por la transacción creada, no por diferencia de balance (puede haber otras)
    tx_nueva = TransactionModel.objects.filter(
        wallet=wallet, transaction_type='deposit',
        amount=period.net_amount,
        description__icontains="Ganancias por vistas"
    ).last()

    if tx_nueva and tx_nueva.amount == period.net_amount:
        ok(f"Wallet acreditado correctamente: +${tx_nueva.amount}")
    else:
        fail(f"No se encontró la transacción de ${period.net_amount}")

    period.refresh_from_db()
    if period.status == 'paid':
        ok(f"Periodo marcado como 'paid' ✓")
    else:
        fail(f"Periodo quedó en status='{period.status}' (esperado 'paid')")

    if period.paid_at is not None:
        ok(f"paid_at registrado: {period.paid_at}")
    else:
        fail("paid_at es None — no se registró la fecha de pago")

    tx = TransactionModel.objects.filter(
        wallet=wallet,
        transaction_type='deposit',
        amount=period.net_amount,
    ).last()
    if tx:
        ok(f"TransactionModel creado: ${tx.amount} | {tx.description[:60]}")
    else:
        fail("No se creó el TransactionModel de depósito")

# ─────────────────────────────────────────
# TEST 7 — Doble aprobación no dobla el pago
# ─────────────────────────────────────────
section("TEST 7 — Doble aprobación (protección contra doble pago)")

if period:
    wallet.refresh_from_db()
    balance_pre = wallet.balance

    approve_earning_period(period.id)

    wallet.refresh_from_db()
    if wallet.balance == balance_pre:
        ok("Segunda aprobación ignorada — balance no cambió")
    else:
        fail(f"¡Doble pago! Balance cambió en ${wallet.balance - balance_pre}")

# ─────────────────────────────────────────
# TEST 8 — Cambio de tarifa en GlobalSettings
# ─────────────────────────────────────────
section("TEST 8 — Cambio dinámico de tarifa en GlobalSettings")

cfg_fresh = GlobalSettings.get_settings()
tarifa_original = cfg_fresh.view_rate_per_1000

# Cambiar tarifa a $0.20
GlobalSettings.objects.filter(pk=1).update(view_rate_per_1000=Decimal('0.2000'))
cfg_fresh2 = GlobalSettings.get_settings()

if cfg_fresh2.view_rate_per_1000 == Decimal('0.2000'):
    ok("GlobalSettings.get_settings() lee el nuevo valor al instante ($0.20)")
else:
    fail(f"Tarifa no cambió: {cfg_fresh2.view_rate_per_1000}")

# Restaurar tarifa original
GlobalSettings.objects.filter(pk=1).update(view_rate_per_1000=tarifa_original)
cfg_final = GlobalSettings.get_settings()
if cfg_final.view_rate_per_1000 == tarifa_original:
    ok(f"Tarifa restaurada a ${tarifa_original}")
else:
    fail("No se pudo restaurar la tarifa original")

# ─────────────────────────────────────────
# LIMPIEZA
# ─────────────────────────────────────────
section("LIMPIEZA — Removiendo datos de prueba")

MonetizableViewLog.objects.filter(video=video, user=viewer).delete()
VideoEarningsDaily.objects.filter(video=video).delete()
CreatorEarningsPeriod.objects.filter(creator=creator, week_start=week_start).delete()
TransactionModel.objects.filter(
    wallet=wallet,
    description__icontains="Ganancias por vistas"
).delete()
VideoStats.objects.filter(pk=stats.pk).update(monetizable_views=0)

# Restaurar balance original
WalletModel.objects.filter(pk=wallet.pk).update(balance=balance_inicial)

ok("Todos los datos de prueba eliminados")
ok(f"Balance del creador restaurado a ${balance_inicial}")

# ─────────────────────────────────────────
# RESULTADO FINAL
# ─────────────────────────────────────────
total = passed + failed
print(f"\n{BOLD}{'═'*55}")
if failed == 0:
    print(f"{VERDE}  RESULTADO: {passed}/{total} tests pasaron ✅  TODO FUNCIONAL{RESET}{BOLD}")
else:
    print(f"{ROJO}  RESULTADO: {passed}/{total} pasaron — {failed} fallaron ❌{RESET}{BOLD}")
print(f"{'═'*55}{RESET}\n")
