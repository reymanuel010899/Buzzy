"""
Buzzy Platform Premium — $5.99/mo
Endpoints:
  POST /api/premium/checkout/        → create Stripe Checkout session
  GET  /api/premium/status/          → check current user premium status
  POST /api/premium/webhook/         → Stripe webhook (activate/cancel)
  POST /api/premium/cancel/          → cancel subscription
"""
import stripe
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny

from .models import BuzzyPremium

stripe.api_key = settings.STRIPE_SECRET_KEY

PREMIUM_PRICE = 5.99
PREMIUM_PRICE_CENTS = 599  # cents


class PremiumStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            premium = request.user.buzzy_premium
            return Response({
                'is_premium': premium.is_active,
                'status': premium.status,
                'expires_at': premium.expires_at,
                'started_at': premium.started_at,
            })
        except BuzzyPremium.DoesNotExist:
            return Response({'is_premium': False, 'status': None})


class PremiumCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # Already premium
        try:
            if user.buzzy_premium.is_active:
                return Response(
                    {'error': 'Ya tienes Buzzy Premium activo.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except BuzzyPremium.DoesNotExist:
            pass

        frontend_url = settings.FRONTEND_URL.rstrip('/')

        try:
            # Get or create Stripe customer
            premium_obj, _ = BuzzyPremium.objects.get_or_create(
                user=user,
                defaults={'status': 'expired'}
            )

            customer_id = premium_obj.stripe_customer_id
            if not customer_id:
                customer = stripe.Customer.create(
                    email=user.email,
                    name=f"{user.first_name} {user.last_name}".strip() or user.username,
                    metadata={'user_id': user.id},
                )
                customer_id = customer.id
                premium_obj.stripe_customer_id = customer_id
                premium_obj.save(update_fields=['stripe_customer_id'])

            # Create checkout session with inline price (no price ID needed)
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                mode='subscription',
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': PREMIUM_PRICE_CENTS,
                        'recurring': {'interval': 'month'},
                        'product_data': {
                            'name': 'Buzzy Premium',
                            'description': 'Sin anuncios · Videos hasta 5 min · Regalos exclusivos',
                        },
                    },
                    'quantity': 1,
                }],
                success_url=f"{frontend_url}/premium/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{frontend_url}/profile",
                metadata={'user_id': str(user.id)},
            )
            return Response({'checkout_url': session.url})

        except stripe.error.StripeError as e:
            return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


class PremiumCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            premium = request.user.buzzy_premium
            if not premium.is_active:
                return Response({'error': 'No tienes Premium activo.'}, status=status.HTTP_400_BAD_REQUEST)

            if premium.stripe_subscription_id:
                stripe.Subscription.modify(
                    premium.stripe_subscription_id,
                    cancel_at_period_end=True,
                )

            premium.status = 'cancelled'
            premium.cancelled_at = timezone.now()
            premium.save(update_fields=['status', 'cancelled_at'])

            return Response({'message': 'Tu Premium se cancelará al final del período actual.'})
        except BuzzyPremium.DoesNotExist:
            return Response({'error': 'No tienes Premium.'}, status=status.HTTP_400_BAD_REQUEST)


class PremiumVerifyView(APIView):
    """Called by frontend after Stripe redirects to /premium/success."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response({'error': 'session_id requerido.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.retrieve(session_id, expand=['subscription'])
            if session.payment_status != 'paid':
                return Response({'error': 'Pago no completado.'}, status=status.HTTP_402_PAYMENT_REQUIRED)

            sub = session.subscription
            user = request.user

            premium, _ = BuzzyPremium.objects.get_or_create(user=user)
            premium.stripe_subscription_id = sub.id
            premium.stripe_customer_id = session.customer
            premium.status = 'active'
            premium.expires_at = timezone.datetime.fromtimestamp(
                sub.current_period_end, tz=timezone.utc
            )
            premium.save()

            return Response({'is_premium': True, 'expires_at': premium.expires_at})

        except stripe.error.StripeError as e:
            return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@csrf_exempt
def premium_webhook(request):
    """Stripe webhook — source of truth for all Premium state changes."""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    webhook_secret = getattr(settings, 'STRIPE_PREMIUM_WEBHOOK_SECRET', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    event_type = event['type']
    data_obj = event['data']['object']

    if event_type == 'checkout.session.completed':
        # First payment completed — activate immediately
        _activate_from_checkout(data_obj)

    elif event_type == 'invoice.paid':
        # Renewal payment — extend period
        sub_id = data_obj.get('subscription')
        if sub_id:
            _activate_by_subscription(sub_id)

    elif event_type in ('customer.subscription.deleted', 'customer.subscription.paused'):
        sub_id = data_obj.get('id')
        if sub_id:
            BuzzyPremium.objects.filter(stripe_subscription_id=sub_id).update(
                status='expired',
                expires_at=timezone.now(),
            )

    elif event_type == 'customer.subscription.updated':
        # Handle cancel_at_period_end = True (user cancelled but still active until end)
        sub_id = data_obj.get('id')
        cancel_at_period_end = data_obj.get('cancel_at_period_end', False)
        if sub_id and cancel_at_period_end:
            BuzzyPremium.objects.filter(stripe_subscription_id=sub_id).update(
                status='cancelled',
                cancelled_at=timezone.now(),
            )

    return HttpResponse(status=200)


def _activate_from_checkout(session_obj):
    """Called on checkout.session.completed — first time a user subscribes."""
    customer_id = session_obj.get('customer')
    sub_id = session_obj.get('subscription')
    user_id = session_obj.get('metadata', {}).get('user_id')

    try:
        premium = BuzzyPremium.objects.get(stripe_customer_id=customer_id)
    except BuzzyPremium.DoesNotExist:
        if not user_id:
            return
        from .models import User
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return
        premium, _ = BuzzyPremium.objects.get_or_create(user=user)

    if sub_id:
        sub = stripe.Subscription.retrieve(sub_id)
        premium.stripe_subscription_id = sub_id
        premium.stripe_customer_id = customer_id
        premium.status = 'active'
        premium.expires_at = timezone.datetime.fromtimestamp(
            sub.current_period_end, tz=timezone.utc
        )
        premium.save()


def _activate_by_subscription(sub_id):
    """Called on invoice.paid — renewal."""
    try:
        premium = BuzzyPremium.objects.get(stripe_subscription_id=sub_id)
    except BuzzyPremium.DoesNotExist:
        return

    sub = stripe.Subscription.retrieve(sub_id)
    premium.status = 'active'
    premium.expires_at = timezone.datetime.fromtimestamp(
        sub.current_period_end, tz=timezone.utc
    )
    premium.save(update_fields=['status', 'expires_at'])
