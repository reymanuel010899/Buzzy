from django.shortcuts import get_object_or_404
import stripe
import secrets
from datetime import timedelta
from django.conf import settings


def _abs_caller(pic_field):
    if not pic_field:
        return None
    s = pic_field.url if hasattr(pic_field, 'url') else str(pic_field)
    if s.startswith("http"):
        return s
    base = settings.BACKEND_URL.rstrip("/")
    return f"{base}{s}" if s.startswith("/") else f"{base}/{s}"
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from django.utils import timezone
from .models import SubscriptionPlan, UserSubscription, CallSession
from .serializers import SubscriptionPlanSerializer, SubscriberListSerializer, CallSessionSerializer
from apps.users.models import User
from apps.users.models import User as UserModel
from .utils import (
    build_channel_name,
    finalize_call_session,
    generate_agora_token_payload,
    generate_agora_uids,
    get_call_payload,
    schedule_call_kill,
    send_call_push_notification,
)
stripe.api_key = settings.STRIPE_SECRET_KEY

class SubscriptionPlanListView(ListAPIView):
    queryset = SubscriptionPlan.objects.filter(is_active=True)
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.IsAuthenticated]

class CreateCheckoutSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        plan_id = request.data.get('plan_id')
        subscribed_to_id = request.data.get('subscribed_to_id')
        
        if not subscribed_to_id:
            return Response({'error': 'subscribed_to_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
            from django.contrib.auth import get_user_model
            User = get_user_model()
            subscribed_to = User.objects.get(id=subscribed_to_id)
            
            # Create Stripe Checkout Session
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {
                                'name': f"Buzzy {plan.name} Subscription to {subscribed_to.username}",
                                **({'description': plan.description} if plan.description else {}),
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
                    'plan_id': str(plan.id),
                    'user_id': str(request.user.id),
                    'subscribed_to_id': str(subscribed_to_id),
                    'type': 'subscription'
                }
            )

            return Response({'url': checkout_session.url})
        except SubscriptionPlan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class CallServiceMixin:
    def _validate_and_prepare(self, request):
        caller = request.user
        subscribed_to_id = request.data.get('subscribed_to_id')
        call_type = (request.data.get('call_type') or 'voice').lower()

        if not subscribed_to_id:
            return None, Response({'error': 'subscribed_to_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        if call_type not in ['voice', 'video']:
            return None, Response({'error': 'call_type debe ser voice o video'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            callee = UserModel.objects.get(id=subscribed_to_id)
        except UserModel.DoesNotExist:
            return None, Response({'error': 'Usuario no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            subscription = UserSubscription.objects.get(
                subscriber=caller,
                subscribed_to=callee,
                is_active=True
            )
        except UserSubscription.DoesNotExist:
            return None, Response({'error': 'No tienes una suscripción activa con este usuario.'}, status=status.HTTP_404_NOT_FOUND)

        is_available = callee.is_currently_available()
        if not is_available:
            return None, Response({
                'error': 'El usuario no está disponible para recibir llamadas en este momento.',
                'availability_error': True,
            }, status=status.HTTP_403_FORBIDDEN)

        if call_type == 'video':
            can_call, message = subscription.can_make_video_call()
            remaining_seconds = subscription.get_remaining_seconds('VIDEO CALLS')
        else:
            can_call, message = subscription.can_make_call()
            remaining_seconds = subscription.get_remaining_seconds('CALLS')

        if not can_call or remaining_seconds <= 0:
            return None, Response({'error': message}, status=status.HTTP_403_FORBIDDEN)

        return {
            'caller': caller,
            'callee': callee,
            'subscription': subscription,
            'call_type': call_type,
            'remaining_seconds': remaining_seconds,
        }, None


class CallInitiateView(CallServiceMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        prepared, error_response = self._validate_and_prepare(request)
        if error_response:
            return error_response

        caller = prepared['caller']
        callee = prepared['callee']
        subscription = prepared['subscription']
        call_type = prepared['call_type']
        remaining_seconds = prepared['remaining_seconds']

        channel_name = build_channel_name(caller.id, callee.id)
        agora_uid_caller = int(secrets.randbelow(900000) + 100000)
        agora_uid_callee = int(secrets.randbelow(900000) + 100000)

        call_session = CallSession.objects.create(
            caller=caller,
            callee=callee,
            subscription=subscription,
            call_type=call_type,
            channel_name=channel_name,
            agora_uid_caller=agora_uid_caller,
            agora_uid_callee=agora_uid_callee,
            allowed_seconds=remaining_seconds,
            status='ringing',
        )

        caller_token = generate_agora_token_payload(channel_name, agora_uid_caller, remaining_seconds, call_session.uuid)
        callee_token = generate_agora_token_payload(channel_name, agora_uid_callee, remaining_seconds, call_session.uuid)
        call_session.agora_token_expire_at = timezone.now() + timedelta(seconds=remaining_seconds)
        call_session.metadata = {
            'caller_token_provider': caller_token['provider'],
            'callee_token_provider': callee_token['provider'],
        }
        call_session.save(update_fields=['agora_token_expire_at', 'metadata'])

        # Notify callee via socket for real-time UI popup
        try:
            import httpx
            _ws_headers = {"X-Broadcast-Secret": settings.BROADCAST_SECRET}
            with httpx.Client() as client:
                client.post(
                    f"{settings.SOCKET_URL}/broadcast-call/",
                    json={
                        "event": "incoming_call",
                        "type": "incoming_call",
                        "call": get_call_payload(call_session, caller_token, callee_token)['callee'],
                        "recipient_id": callee.id,
                        "caller_username": caller.username,
                        "caller_avatar": _abs_caller(caller.profile_picture),
                    },
                    headers=_ws_headers,
                    timeout=2.0
                )
        except Exception:
            pass

        schedule_call_kill(call_session)

        # Send push notification
        push_payload = {
            'call_id': str(call_session.uuid),
            'call_type': call_type,
            'caller_username': caller.username,
            'caller_avatar': _abs_caller(caller.profile_picture),
            'channel_name': channel_name,
        }
        push_result = send_call_push_notification(callee, push_payload)
        return Response({
            'status': 'success',
            'message': 'Videollamada iniciada correctamente.' if call_type == 'video' else 'Llamada iniciada correctamente.',
            'call': get_call_payload(call_session, caller_token, callee_token)['caller'],
            'token': caller_token['token'],
            'app_id': settings.AGORA_APP_ID,
            'receiver_push': push_result,
        }, status=status.HTTP_200_OK)


class StartCallView(CallInitiateView):
    pass


class CallAcceptView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        call_id = request.data.get('call_id')
        if not call_id:
            return Response({'error': 'call_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            call_session = CallSession.objects.get(uuid=call_id)
        except CallSession.DoesNotExist:
            return Response({'error': 'Llamada no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.id != call_session.callee_id:
            return Response({'error': 'No autorizado para aceptar esta llamada.'}, status=status.HTTP_403_FORBIDDEN)

        if call_session.status != 'ringing':
            return Response({'error': f'No se puede aceptar una llamada en estado {call_session.status}.'}, status=status.HTTP_400_BAD_REQUEST)

        call_session.status = 'active'
        call_session.answered_at = timezone.now()
        call_session.save(update_fields=['status', 'answered_at'])

        # Notify caller via socket
        try:
            import httpx
            _ws_headers = {"X-Broadcast-Secret": settings.BROADCAST_SECRET}
            with httpx.Client() as client:
                client.post(
                    f"{settings.SOCKET_URL}/broadcast-call/",
                    json={
                        "event": "call_accepted",
                        "type": "call_accepted",
                        "uuid": str(call_session.uuid),
                        "recipient_id": call_session.caller_id,
                        "answered_at": call_session.answered_at.isoformat(),
                    },
                    headers=_ws_headers,
                    timeout=2.0
                )
        except Exception:
            pass

        # Generar token para el callee
        from .utils import generate_agora_token_payload
        agora_payload = generate_agora_token_payload(
            call_session.channel_name,
            call_session.agora_uid_callee,
            call_session.allowed_seconds,
            str(call_session.uuid)
        )
        print(agora_payload, "*******")
        return Response({
            'status': 'success',
            'message': 'Llamada aceptada.',
            'call': CallSessionSerializer(call_session).data,
            'token': agora_payload['token'],
            'app_id': settings.AGORA_APP_ID,
        }, status=status.HTTP_200_OK)


class CallEndView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        call_id = request.data.get('call_id')
        reason = request.data.get('reason') or 'ended'
        consumed_seconds = request.data.get('consumed_seconds')

        if not call_id:
            return Response({'error': 'call_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            call_session = CallSession.objects.select_related('subscription').get(uuid=call_id)
        except CallSession.DoesNotExist:
            return Response({'error': 'Llamada no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.id not in [call_session.caller_id, call_session.callee_id]:
            return Response({'error': 'No autorizado para cerrar esta llamada.'}, status=status.HTTP_403_FORBIDDEN)

        finalized = finalize_call_session(
            call_session,
            reason=reason,
            consumed_seconds=consumed_seconds,
            force_close=False,
        )

        # Notify other party via socket
        try:
            other_id = call_session.callee_id if request.user.id == call_session.caller_id else call_session.caller_id
            import httpx
            _ws_headers = {"X-Broadcast-Secret": settings.BROADCAST_SECRET}
            with httpx.Client() as client:
                client.post(
                    f"{settings.SOCKET_URL}/broadcast-call/",
                    json={
                        "event": "call_ended",
                        "type": "call_ended",
                        "uuid": str(call_session.uuid),
                        "recipient_id": other_id,
                        "reason": reason,
                    },
                    headers=_ws_headers,
                    timeout=2.0
                )
        except Exception:
            pass

        return Response({
            'status': 'success',
            'message': 'Llamada cerrada correctamente.',
            'call': CallSessionSerializer(finalized).data,
        }, status=status.HTTP_200_OK)


class AgoraCallWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        # Verificar secret para que solo nuestro backend pueda cerrar llamadas
        webhook_secret = getattr(settings, 'AGORA_WEBHOOK_SECRET', '')
        if webhook_secret:
            incoming = request.headers.get('X-Agora-Secret', '')
            if not secrets.compare_digest(incoming, webhook_secret):
                return Response({'error': 'Forbidden'}, status=403)

        call_id = request.data.get('call_id')
        duration_seconds = request.data.get('duration_seconds') or request.data.get('duration') or 0
        reason = request.data.get('reason') or 'agora_webhook'

        if not call_id:
            return Response({'error': 'call_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            call_session = CallSession.objects.select_related('subscription').get(uuid=call_id)
        except CallSession.DoesNotExist:
            return Response({'error': 'Llamada no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        finalized = finalize_call_session(
            call_session,
            reason=reason,
            consumed_seconds=duration_seconds,
            force_close=False,
        )
        return Response({
            'status': 'success',
            'call': CallSessionSerializer(finalized).data,
        }, status=status.HTTP_200_OK)

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

            elif event_type == 'subscription' or not event_type:
                # Original subscription logic
                plan_id = metadata.get('plan_id')
                subscribed_to_id = metadata.get('subscribed_to_id')
                stripe_subscription_id = session.get('subscription')
                stripe_customer_id = session.get('customer')
                
                print(f"Processing subscription webhook: user_id={user_id}, subscribed_to_id={subscribed_to_id}, plan_id={plan_id}")

                if user_id and plan_id and subscribed_to_id:
                    try:
                        from django.contrib.auth import get_user_model
                        User = get_user_model()
                        subscriber = User.objects.get(id=user_id)
                        subscribed_to = User.objects.get(id=subscribed_to_id)
                        
                        user_sub, created = UserSubscription.objects.get_or_create(
                            subscriber=subscriber, 
                            subscribed_to=subscribed_to
                        )
                        plan = SubscriptionPlan.objects.get(id=plan_id)
                        
                        user_sub.activate(
                            plan=plan,
                            stripe_subscription_id=stripe_subscription_id,
                            stripe_customer_id=stripe_customer_id
                        )
                        print(f"Successfully activated subscription for {user_id} -> {subscribed_to_id} via webhook")
                    except Exception as e:
                        print(f"Error processing subscription webhook for user {user_id}: {e}")

        elif event['type'] in ('invoice.payment_succeeded', 'invoice.paid'):
            invoice = event['data']['object']
            stripe_subscription_id = invoice.get('subscription')
            amount_paid = invoice.get('amount_paid', 0)
            stripe_invoice_id = invoice.get('id')

            if not stripe_subscription_id or amount_paid == 0:
                return HttpResponse(status=200)

            try:
                from django.contrib.auth import get_user_model
                from apps.wallet.models import WalletModel, TransactionModel

                user_sub = UserSubscription.objects.select_related('subscriber').get(
                    stripe_subscription_id=stripe_subscription_id
                )
                wallet = WalletModel.objects.get(user=user_sub.subscriber)

                # Avoid duplicate transactions for the same invoice
                if not TransactionModel.objects.filter(payment_id=stripe_invoice_id).exists():
                    TransactionModel.objects.create(
                        wallet=wallet,
                        transaction_type='withdrawal',
                        status='completed',
                        amount=round(amount_paid / 100, 2),
                        description="Cuota de suscripción vía Stripe",
                        payment_id=stripe_invoice_id,
                    )
            except UserSubscription.DoesNotExist:
                print(f"No UserSubscription found for stripe_subscription_id={stripe_subscription_id}")
            except Exception as e:
                print(f"Error processing invoice webhook: {e}")

        return HttpResponse(status=200)

class VerifyCheckoutSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response({'error': 'Missing session_id'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            
            # Proactive activation if session is paid/complete
            if session.payment_status == 'paid' or session.status == 'complete':
                user_id = session.client_reference_id or session.metadata.get('user_id')
                plan_id = session.metadata.get('plan_id')
                subscribed_to_id = session.metadata.get('subscribed_to_id')
                
                if user_id and plan_id and subscribed_to_id:
                    print(f"Verifying session: user_id={user_id}, subscribed_to_id={subscribed_to_id}, plan_id={plan_id}")
                    try:
                        from django.contrib.auth import get_user_model
                        User = get_user_model()
                        subscriber = User.objects.get(id=user_id)
                        subscribed_to = User.objects.get(id=subscribed_to_id)
                        
                        user_sub, created = UserSubscription.objects.get_or_create(
                            subscriber=subscriber,
                            subscribed_to=subscribed_to
                        )
                        plan = SubscriptionPlan.objects.get(id=plan_id)
                        
                        user_sub.activate(
                            plan=plan,
                            stripe_subscription_id=session.subscription,
                            stripe_customer_id=session.customer
                        )
                        print(f"Successfully activated subscription for {user_id} -> {subscribed_to_id} via verification view")
                    except Exception as e:
                        print(f"Error activating subscription via verification view: {e}")

            return Response({
                'id': session.id,
                'payment_status': session.payment_status,
                'status': session.status,
                'amount_total': session.amount_total / 100,
                'currency': session.currency,
                'metadata': session.metadata
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class SubscribersListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, username):
        target_user = get_object_or_404(User, username=username)
        # People who are subscribed TO target_user
        subscribers = UserSubscription.objects.filter(subscribed_to=target_user, is_active=True).select_related('subscriber', 'plan')
        
        serializer = SubscriberListSerializer(subscribers, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
