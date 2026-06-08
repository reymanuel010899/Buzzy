"""
auto_review_campaign — Celery task
===================================
Analiza automáticamente una campaña recién pagada:

  1. Valida texto (título, descripción) — palabras prohibidas
  2. Valida URL de destino — responde y no es dominio de spam
  3. Valida creativo (imagen/video) — existe y tiene tamaño razonable
  4. Verifica presupuesto mínimo

Si todo OK  → status = ACTIVE   (campaña live en segundos)
Si algo falla → status = IN_REVIEW con razón específica para moderador humano
"""

from __future__ import annotations

import logging
import os
import re
import urllib.request
from typing import List, Tuple

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# ─── Listas de control ────────────────────────────────────────────────────────

BANNED_WORDS: List[str] = [
    # Spam / estafas
    "gana dinero fácil", "ganar dinero rápido", "hazte rico", "trabaja desde casa",
    "inversión garantizada", "sin riesgo", "100% garantizado", "mlm", "pirámide",
    "crypto pump", "nft gratis", "airdrop",
    # Contenido adulto
    "xxx", "porno", "porno", "adult", "sexy", "18+", "onlyfans",
    # Violencia / odio
    "matar", "terrorismo", "bomba", "arma", "droga", "cocaína",
    # Medicamentos / salud falsa
    "cura milagrosa", "pierde peso", "baja de peso garantizado", "viagra", "cialis",
    # Juegos de azar no regulados
    "casino gratis", "apuesta segura",
]

SPAM_DOMAINS: List[str] = [
    "bit.ly", "tinyurl.com", "goo.gl", "ow.ly", "t.co",
    "click.com", "clickbank.net", "adf.ly",
]

MIN_BUDGET = 1.0   # USD mínimo total


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _check_text(text: str) -> Tuple[bool, str]:
    """Retorna (ok, reason). ok=False significa contenido prohibido."""
    if not text:
        return True, ""
    normalized = text.lower()
    for word in BANNED_WORDS:
        if word in normalized:
            return False, f"Texto contiene contenido no permitido: '{word}'"
    return True, ""


def _check_url(url: str) -> Tuple[bool, str]:
    """Verifica que la URL sea válida, accesible y no sea dominio de spam."""
    if not url:
        return True, ""  # URL opcional

    # Formato básico
    if not re.match(r'^https?://', url):
        return False, f"URL de destino inválida (debe empezar con http/https): {url}"

    # Dominio de spam
    for domain in SPAM_DOMAINS:
        if domain in url:
            return False, f"Dominio no permitido en URL de destino: {domain}"

    # Accesibilidad (timeout 8s)
    try:
        req = urllib.request.Request(url, method='HEAD',
                                     headers={'User-Agent': 'BuzzyAdsBot/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status >= 400:
                return False, f"URL de destino retorna error HTTP {resp.status}"
    except Exception as e:
        # No bloqueamos por timeout de red — enviamos a revisión humana
        return False, f"No se pudo verificar la URL de destino: {e}"

    return True, ""


def _check_creative(creative) -> Tuple[bool, str]:
    """Verifica que el archivo creativo exista y tenga un tamaño razonable."""
    if not creative:
        return False, "La campaña no tiene un creativo (imagen/video) asociado."

    media = getattr(creative, 'media_file', None)
    if not media:
        return False, "El creativo no tiene archivo multimedia adjunto."

    # Verificar que el archivo existe físicamente
    try:
        size = media.size  # bytes
    except Exception:
        return False, "El archivo del creativo no se puede leer o no existe."

    max_size = 100 * 1024 * 1024  # 100 MB
    if size > max_size:
        return False, f"El archivo del creativo supera el tamaño máximo permitido (100 MB)."

    if size == 0:
        return False, "El archivo del creativo está vacío."

    return True, ""


def _check_budget(budget) -> Tuple[bool, str]:
    if not budget:
        return False, "La campaña no tiene presupuesto configurado."
    if float(budget.total_budget) < MIN_BUDGET:
        return False, f"El presupuesto total mínimo es ${MIN_BUDGET} USD."
    return True, ""


# ─── Task principal ───────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name='apps.ads.tasks.auto_review_campaign',
)
def auto_review_campaign(self, campaign_id: int) -> dict:
    """
    Revisa automáticamente una campaña y la activa o envía a revisión humana.
    """
    from .models import AdCampaign, AdReview

    logger.info(f"[AdsReview] Iniciando revisión automática — campaign_id={campaign_id}")

    try:
        campaign = AdCampaign.objects.select_related(
            'creative', 'budget', 'audience'
        ).get(id=campaign_id)
    except AdCampaign.DoesNotExist:
        logger.error(f"[AdsReview] Campaña {campaign_id} no encontrada.")
        return {'status': 'error', 'reason': 'Campaign not found'}

    # Solo revisar si está en IN_REVIEW
    if campaign.status != 'IN_REVIEW':
        logger.info(f"[AdsReview] Campaña {campaign_id} no está en IN_REVIEW (status={campaign.status}). Saltando.")
        return {'status': 'skipped', 'campaign_status': campaign.status}

    creative = getattr(campaign, 'creative', None)
    budget   = getattr(campaign, 'budget', None)

    issues: List[str] = []

    # 1. Título
    ok, reason = _check_text(campaign.name)
    if not ok:
        issues.append(f"Nombre: {reason}")

    # 2. Texto del creativo (título + descripción)
    if creative:
        ok, reason = _check_text(getattr(creative, 'title', ''))
        if not ok:
            issues.append(f"Título del anuncio: {reason}")

        ok, reason = _check_text(getattr(creative, 'description', ''))
        if not ok:
            issues.append(f"Descripción: {reason}")

        # 3. URL de destino
        ok, reason = _check_url(getattr(creative, 'destination_url', ''))
        if not ok:
            issues.append(f"URL: {reason}")

        # 4. Archivo multimedia
        ok, reason = _check_creative(creative)
        if not ok:
            issues.append(f"Creativo: {reason}")
    else:
        issues.append("Creativo: La campaña no tiene creativo asociado.")

    # 5. Presupuesto
    ok, reason = _check_budget(budget)
    if not ok:
        issues.append(f"Presupuesto: {reason}")

    # ─── Decisión ─────────────────────────────────────────────────────────────
    if issues:
        # Enviamos a revisión humana con las razones
        rejection_summary = " | ".join(issues)
        campaign.status = 'IN_REVIEW'
        campaign.rejection_reason = f"[Auto-revisión] Requiere revisión humana: {rejection_summary}"
        campaign.save()

        # Actualizar AdReview si existe
        review = getattr(campaign, 'review', None)
        if review:
            review.decision = 'PENDING'
            review.rejection_reason = rejection_summary
            review.save()

        logger.warning(f"[AdsReview] Campaña {campaign_id} → IN_REVIEW. Problemas: {rejection_summary}")
        return {
            'status': 'in_review',
            'campaign_id': campaign_id,
            'issues': issues,
        }
    else:
        # Todo OK — activar automáticamente
        campaign.status = 'ACTIVE'
        campaign.rejection_reason = ''
        campaign.save()

        # Marcar review como aprobado automáticamente
        review = getattr(campaign, 'review', None)
        if review:
            review.decision    = 'APPROVED'
            review.reviewed_at = timezone.now()
            review.reviewed_by = None  # aprobado por sistema
            review.save()

        logger.info(f"[AdsReview] Campaña {campaign_id} → ACTIVE (aprobación automática).")
        return {
            'status': 'approved',
            'campaign_id': campaign_id,
        }


@shared_task(name='apps.ads.tasks.expire_campaigns')
def expire_campaigns():
    """
    Runs every 15 minutes via Celery Beat.
    Marks ACTIVE campaigns as COMPLETED when:
      - end_date has passed, OR
      - spent_amount >= total_budget
    """
    from django.utils import timezone
    from .models import AdCampaign, AdBudget
    from django.db.models import F, Q

    now = timezone.now()

    # Expired by date
    expired_by_date = AdCampaign.objects.filter(
        status='ACTIVE',
        end_date__isnull=False,
        end_date__lt=now,
    )
    count_date = expired_by_date.update(status='COMPLETED')

    # Expired by budget — find campaigns where spent >= total
    overspent_ids = AdBudget.objects.filter(
        campaign__status='ACTIVE',
        spent_amount__gte=F('total_budget'),
    ).values_list('campaign_id', flat=True)

    count_budget = AdCampaign.objects.filter(pk__in=overspent_ids).update(status='COMPLETED')

    logger.info(
        f"[expire_campaigns] Completed {count_date} by date, {count_budget} by budget."
    )
    return {'expired_by_date': count_date, 'expired_by_budget': count_budget}
