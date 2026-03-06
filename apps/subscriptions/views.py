import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .models import SubscriptionPlan, UserSubscription
from .serializers import SubscriptionPlanSerializer

stripe.api_key = settings.STRIPE_SECRET_KEY

class SubscriptionPlanListView(ListAPIView):
    queryset = SubscriptionPlan.objects.filter(is_active=True)
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.IsAuthenticated]

class CreateCheckoutSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        plan_id = request.data.get('plan_id')
        try:
            plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
            
            # Create Stripe Checkout Session
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {
                                'name': f"Buzzy {plan.name} Subscription",
                                'description': plan.description,
                            },
                            'unit_amount': int(plan.price * 100),
                            'recurring': {
                                'interval': 'month',
                            },
                        },
                        'quantity': 1,
                    },
                ],
                mode='subscription',
                success_url=settings.FRONTEND_URL + '/subscription-success?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=settings.FRONTEND_URL + '/subscription-cancel',
                client_reference_id=str(request.user.id),
                metadata={
                    'plan_id': plan.id,
                    'user_id': request.user.id,
                }
            )

            return Response({'url': checkout_session.url})
        except SubscriptionPlan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class StartCallView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        try:
            subscription = user.subscription
            can_call, message = subscription.can_make_call()
            
            if not can_call:
                return Response({'error': message}, status=status.HTTP_403_FORBIDDEN)
            
            # Increment call count
            subscription.calls_this_month += 1
            subscription.save()
            
            return Response({
                'status': 'success',
                'message': 'Llamada iniciada correctamente.',
                'calls_remaining': self._get_limit(subscription.plan.name) - subscription.calls_this_month
            })
            
        except UserSubscription.DoesNotExist:
            return Response({'error': 'No tienes un registro de suscripción.'}, status=status.HTTP_404_NOT_FOUND)

    def _get_limit(self, plan_name):
        if plan_name == 'PLUS':
            return 3
        if plan_name == 'FRIEND':
            return 10
        return 0

class StripeWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        event = None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError as e:
            return HttpResponse(status=400)

        # Handle the event
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            user_id = session.get('client_reference_id')
            metadata = session.get('metadata', {})
            event_type = metadata.get('type')
            
            if event_type == 'wallet_deposit':
                amount = metadata.get('amount')
                if user_id and amount:
                    try:
                        from apps.wallet.models import WalletModel, TransactionModel
                        wallet = WalletModel.objects.get(user_id=user_id)
                        TransactionModel.objects.create(
                            wallet=wallet,
                            transaction_type='deposit',
                            status='completed',
                            amount=float(amount),
                            description=f"Recarga de billetera vía Stripe",
                            payment_id=session.get('id')
                        )
                        # Signal 'update_wallet_balance' will update the balance
                    except Exception as e:
                        print(f"Error processing wallet deposit: {e}")

            else:
                # Original subscription logic
                plan_id = metadata.get('plan_id')
                stripe_subscription_id = session.get('subscription')
                stripe_customer_id = session.get('customer')

                if user_id and plan_id:
                    try:
                        user_sub = UserSubscription.objects.get(user_id=user_id)
                        plan = SubscriptionPlan.objects.get(id=plan_id)
                        user_sub.plan = plan
                        user_sub.stripe_subscription_id = stripe_subscription_id
                        user_sub.stripe_customer_id = stripe_customer_id
                        user_sub.is_active = True
                        user_sub.save()
                    except Exception as e:
                        print(f"Error processing subscription webhook: {e}")

        return HttpResponse(status=200)
