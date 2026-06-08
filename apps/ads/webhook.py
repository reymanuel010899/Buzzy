import stripe
import logging
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import AdCampaign, AdReview

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        return HttpResponse(status=400)
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']

        # Only handle ad campaign payments
        if session.get('metadata', {}).get('type') != 'ad_campaign':
            return HttpResponse(status=200)

        campaign_id = session.get('metadata', {}).get('campaign_id')
        payment_status = session.get('payment_status')

        if not campaign_id:
            logger.error("Webhook: no campaign_id in metadata")
            return HttpResponse(status=200)

        if payment_status != 'paid':
            logger.warning(f"Webhook: session completed but payment_status={payment_status}")
            return HttpResponse(status=200)

        try:
            campaign = AdCampaign.objects.select_related('budget').get(pk=campaign_id)

            # Idempotency — skip if already processed
            if campaign.status not in ('DRAFT', 'IN_REVIEW'):
                return HttpResponse(status=200)

            campaign.status = 'IN_REVIEW'
            campaign.save()

            AdReview.objects.get_or_create(campaign=campaign)

            from .tasks import auto_review_campaign
            auto_review_campaign.delay(campaign.id)

            logger.info(f"Webhook: campaign {campaign_id} set to IN_REVIEW via webhook")

        except AdCampaign.DoesNotExist:
            logger.error(f"Webhook: campaign {campaign_id} not found")

    elif event['type'] == 'checkout.session.expired':
        # Session expired without payment — keep campaign as DRAFT so user can retry
        session = event['data']['object']
        campaign_id = session.get('metadata', {}).get('campaign_id')
        logger.info(f"Webhook: checkout session expired for campaign {campaign_id}")

    return HttpResponse(status=200)
