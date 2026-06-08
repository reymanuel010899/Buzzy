import os
import stripe
from decimal import Decimal, InvalidOperation
from apps.wallet.models import WalletModel, TransactionModel
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.generics import ListAPIView
from .models import AIStyle, AIGenerationHistory, AIPackage, AIWallet
from .serializers import AIStyleSerializer, AIGenerationHistorySerializer, AIPackageSerializer
from .tasks import generate_ai_media, moderate_ai_media

stripe.api_key = settings.STRIPE_SECRET_KEY


class AIGenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user       = request.user
        prompt     = request.data.get("prompt", "").strip()
        media_type = request.data.get("type", "image")
        style_slug = request.data.get("style", "realistic")
        duration   = int(request.data.get("duration", 6))

        if not prompt:
            return Response({"error": "El prompt es requerido."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ai_wallet = AIWallet.get_or_create_for(user)

            # ── Verificar créditos en AIWallet ──────────────────────────────
            if media_type == "image":
                can, msg = ai_wallet.can_generate_image()
            else:
                can, msg = ai_wallet.can_generate_video(duration)

            if not can:
                return Response({"error": msg}, status=status.HTTP_403_FORBIDDEN)

            # ── Guardar imagen de referencia en disco y pasar la ruta al worker ─
            ref_image_path = None
            ref_mime       = None
            if request.FILES.get("reference_image"):
                try:
                    import tempfile, os
                    reference_image = request.FILES["reference_image"]
                    ref_mime = reference_image.content_type or "image/jpeg"
                    suffix = ".jpg" if "jpeg" in ref_mime else f".{ref_mime.split('/')[-1]}"
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp")
                    for chunk in reference_image.chunks():
                        tmp.write(chunk)
                    tmp.close()
                    ref_image_path = tmp.name
                except Exception as exc:
                    print(f"⚠️ Error guardando reference_image: {exc}")

            # ── Crear registro en historial ─────────────────────────────────
            sub_style = AIStyle.objects.filter(slug=style_slug).first()
            history = AIGenerationHistory.objects.create(
                user       = user,
                prompt     = prompt,
                media_type = media_type,
                style      = sub_style,
                status     = "pending",
            )

            # ── Encolar tarea Celery ─────────────────────────────────────────
            task = generate_ai_media.delay(
                history_id     = history.id,
                media_type     = media_type,
                style_slug     = style_slug,
                duration       = duration,
                ref_image_path = ref_image_path,
                ref_mime       = ref_mime,
            )

            return Response({
                "message":        "Generación en proceso. Consulta el estado con el history_id.",
                "history_id":     history.id,
                "celery_task_id": task.id,
                "video_credits":  ai_wallet.video_credits,
                "image_credits":  ai_wallet.image_credits,
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as exc:
            print(f"AIGenerateView error: {exc}")
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AIGenerationStatusView(APIView):
    """Devuelve el estado y la URL final de una generación en curso."""
    permission_classes = [IsAuthenticated]

    def get(self, request, history_id):
        try:
            history = AIGenerationHistory.objects.get(id=history_id, user=request.user)
        except AIGenerationHistory.DoesNotExist:
            return Response({"error": "No encontrado."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "history_id": history.id,
            "status":     history.status,
            "media_url":  history.media_url or None,
            "media_type": history.media_type,
        })


class ListAIStylesView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AIStyleSerializer
    queryset = AIStyle.objects.filter(is_active=True).prefetch_related('templates')


class ListAIGenerationHistoryView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AIGenerationHistorySerializer

    def get_queryset(self):
        return AIGenerationHistory.objects.filter(user=self.request.user)


class PublishAIContentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        history_id = request.data.get("history_id")
        if not history_id:
            return Response({"error": "history_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            history_item = AIGenerationHistory.objects.get(id=history_id, user=request.user)

            from .models import Video, Category
            category = Category.objects.filter(name='Default').first()

            video = Video.objects.create(
                user_id=request.user,
                category=category,
                video_url=history_item.media_url,
                status='active',
                safety_label='safe',
                is_safe=True,
                thumbnail_url=history_item.media_url,
                description=history_item.prompt,
                tags={"tags": []},
                media_type=history_item.media_type,
                duration=5 if history_item.media_type == 'video' else 0
            )

            moderate_ai_media.delay(video.id)

            return Response({
                "message":  "Publicado exitosamente en tu perfil",
                "video_id": video.id,
                "uuid":     video.uuid
            }, status=status.HTTP_201_CREATED)

        except AIGenerationHistory.DoesNotExist:
            return Response({"error": "No se encontró el elemento en el historial"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AICreditsView(APIView):
    """Devuelve los créditos de video e imagen del AIWallet del usuario."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ai_wallet = AIWallet.get_or_create_for(request.user)
        return Response({
            'video_credits': ai_wallet.video_credits,
            'image_credits': ai_wallet.image_credits,
        })


class AIPackageListView(ListAPIView):
    """Lista los paquetes AI disponibles para comprar."""
    permission_classes = [IsAuthenticated]
    serializer_class = AIPackageSerializer
    queryset = AIPackage.objects.filter(is_active=True).order_by('order', 'price')


class AIPackagePurchaseView(APIView):
    """Compra un paquete AI descontando del wallet del usuario y carga créditos en AIWallet."""
    permission_classes = [IsAuthenticated]

    # $0.33/video → 3 videos por dólar (mejor que cualquier paquete)
    # $0.50/imagen → 2 imágenes por dólar
    CUSTOM_VIDEOS_PER_DOLLAR = 3
    CUSTOM_IMAGES_PER_DOLLAR = 2

    def post(self, request):
        package_id    = request.data.get('package_id')
        custom_amount = request.data.get('custom_amount')

        if not package_id and not custom_amount:
            return Response({'error': 'Se requiere package_id o custom_amount.'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Resolver precio y créditos ──────────────────────────────────────
        if package_id:
            try:
                package = AIPackage.objects.get(id=package_id, is_active=True)
                price  = package.price
                videos = package.videos_count
                images = package.images_count
                label  = package.name
            except AIPackage.DoesNotExist:
                return Response({'error': 'Paquete no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            try:
                amount = Decimal(str(custom_amount))
                if amount < Decimal('0.50'):
                    return Response({'error': 'El monto mínimo es $0.50.'}, status=status.HTTP_400_BAD_REQUEST)
            except (InvalidOperation, ValueError):
                return Response({'error': 'Monto inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            price  = amount
            videos = int(amount * self.CUSTOM_VIDEOS_PER_DOLLAR)
            images = int(amount * self.CUSTOM_IMAGES_PER_DOLLAR)
            label  = f'Paquete personalizado ${amount}'

        # ── Verificar wallet de dinero ──────────────────────────────────────
        wallet = WalletModel.objects.filter(user=request.user, wallet_type='main').first()
        if not wallet:
            return Response({'error': 'No tienes una billetera activa.', 'insufficient_funds': True}, status=status.HTTP_402_PAYMENT_REQUIRED)

        if wallet.balance < price:
            return Response({
                'error': f'Saldo insuficiente. Tienes ${wallet.balance:.2f} y el paquete cuesta ${price:.2f}.',
                'insufficient_funds': True,
                'balance':  str(wallet.balance),
                'required': str(price),
            }, status=status.HTTP_402_PAYMENT_REQUIRED)

        # ── Descontar del wallet de dinero ──────────────────────────────────
        wallet.balance -= price
        wallet.save(update_fields=['balance'])

        TransactionModel.objects.create(
            wallet=wallet,
            transaction_type='withdrawal',
            status='completed',
            amount=price,
            description=f'Compra IA — {label}: +{videos} videos +{images} imágenes',
        )

        # ── Agregar créditos al AIWallet ────────────────────────────────────
        ai_wallet = AIWallet.get_or_create_for(request.user)
        ai_wallet.add_credits(videos=videos, images=images)

        return Response({
            'message':       f'¡Compra exitosa! +{videos} videos y +{images} imágenes añadidos.',
            'videos_added':  videos,
            'images_added':  images,
            'video_credits': ai_wallet.video_credits,
            'image_credits': ai_wallet.image_credits,
            'wallet_balance': str(wallet.balance),
        }, status=status.HTTP_200_OK)


class AIPackageCheckoutView(APIView):
    """Crea una sesión de Stripe Checkout para comprar créditos IA."""
    permission_classes = [IsAuthenticated]

    CUSTOM_VIDEOS_PER_DOLLAR = 3
    CUSTOM_IMAGES_PER_DOLLAR = 2

    def post(self, request):
        package_id    = request.data.get('package_id')
        custom_amount = request.data.get('custom_amount')

        if not package_id and not custom_amount:
            return Response({'error': 'Se requiere package_id o custom_amount.'}, status=status.HTTP_400_BAD_REQUEST)

        if package_id:
            try:
                package = AIPackage.objects.get(id=package_id, is_active=True)
                price   = float(package.price)
                videos  = package.videos_count
                images  = package.images_count
                label   = package.name
            except AIPackage.DoesNotExist:
                return Response({'error': 'Paquete no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            try:
                price = float(Decimal(str(custom_amount)))
                if price < 0.50:
                    return Response({'error': 'El monto mínimo es $0.50.'}, status=status.HTTP_400_BAD_REQUEST)
            except (InvalidOperation, ValueError):
                return Response({'error': 'Monto inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            videos = int(price * self.CUSTOM_VIDEOS_PER_DOLLAR)
            images = int(price * self.CUSTOM_IMAGES_PER_DOLLAR)
            label  = f'Paquete personalizado ${price:.2f}'

        frontend_url = settings.FRONTEND_URL.rstrip('/')
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f'Buzzy IA — {label}',
                            'description': f'+{videos} videos · +{images} imágenes',
                        },
                        'unit_amount': int(price * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=f'{frontend_url}/ai-credits-success?session_id={{CHECKOUT_SESSION_ID}}',
                cancel_url=f'{frontend_url}/',
                client_reference_id=str(request.user.id),
                metadata={
                    'type':       'ai_credits',
                    'user_id':    str(request.user.id),
                    'videos':     str(videos),
                    'images':     str(images),
                    'price':      str(price),
                }
            )
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'url': session.url, 'session_id': session.id})


class AIPackageCheckoutVerifyView(APIView):
    """Verifica el pago de Stripe y acredita los créditos IA. Idempotente."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response({'error': 'Missing session_id'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if session.payment_status != 'paid':
            return Response({'paid': False, 'status': session.payment_status})

        metadata = session.metadata or {}
        if metadata.get('type') != 'ai_credits':
            return Response({'error': 'Sesión inválida.'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = metadata.get('user_id')
        videos  = int(metadata.get('videos', 0))
        images  = int(metadata.get('images', 0))

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'Usuario no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        # Idempotencia: solo acreditar si no se procesó antes
        already_processed = TransactionModel.objects.filter(payment_id=session_id).exists()
        if not already_processed:
            ai_wallet = AIWallet.get_or_create_for(user)
            ai_wallet.add_credits(videos=videos, images=images)

            wallet, _ = WalletModel.objects.get_or_create(user=user)
            TransactionModel.objects.create(
                wallet=wallet,
                transaction_type='deposit',
                status='completed',
                amount=Decimal(str(metadata.get('price', '0'))),
                description=f'Compra IA vía Stripe — +{videos} videos +{images} imágenes',
                payment_id=session_id,
            )

        ai_wallet = AIWallet.get_or_create_for(user)
        return Response({
            'paid':          True,
            'videos_added':  videos,
            'images_added':  images,
            'video_credits': ai_wallet.video_credits,
            'image_credits': ai_wallet.image_credits,
        })
