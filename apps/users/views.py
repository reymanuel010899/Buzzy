import uuid
import secrets
import re
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.cache import cache
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

# from Buzzy.apps.recommendations.utils import get_redis_client
from .utils import generate_reset_code, send_recovery_email
import requests as http_requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlencode
from django.conf import settings


def _abs_media(path):
    if not path:
        return None
    s = str(path)
    if s.startswith('http'):
        return s
    from django.conf import settings as _s
    base = _s.BACKEND_URL.rstrip('/')
    return f'{base}{s}' if s.startswith('/') else f'{base}/{s}'

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.wallet.models import WalletModel
from apps.recommendations.utils import get_redis_client
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status
from apps.videos.serializers import  VideoZerializer
from apps.videos.models import Video
from .models import Availability, User, SocialAccount, UserSecurity
from .serializers import DetailedUserSerializer, SocialAccountSerializer
from apps.videos.models import ChatRoom, Notification
from apps.videos.views import create_and_broadcast_notification
from apps.subscriptions.models import UserSubscription
from apps.subscriptions.utils import send_push_notification


CHAT_PIN_RATE_LIMIT_MAX_ATTEMPTS = 5
CHAT_PIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
CHAT_PIN_VERIFICATION_WINDOW_MINUTES = 5
_chat_pin_signer = TimestampSigner(salt="buzzy-hidden-chat-pin")


def _get_user_security(user: User) -> UserSecurity:
    security, _ = UserSecurity.objects.get_or_create(user=user)
    return security


def _pin_rate_limit_key(user: User) -> str:
    return f"chat-pin-failures:{user.id}"


def _pin_block_key(user: User) -> str:
    return f"chat-pin-blocked-until:{user.id}"


def _reset_pin_rate_limit(user: User) -> None:
    cache.delete(_pin_rate_limit_key(user))
    cache.delete(_pin_block_key(user))


def _register_failed_pin_attempt(user: User):
    block_key = _pin_block_key(user)
    if cache.get(block_key):
        return True

    attempts_key = _pin_rate_limit_key(user)
    attempts = cache.get(attempts_key, 0) + 1
    cache.set(attempts_key, attempts, CHAT_PIN_RATE_LIMIT_WINDOW_SECONDS)
    if attempts >= CHAT_PIN_RATE_LIMIT_MAX_ATTEMPTS:
        cache.set(block_key, True, CHAT_PIN_RATE_LIMIT_WINDOW_SECONDS)
        return True
    return False


def _is_hidden_access_verified(security: UserSecurity) -> bool:
    return security.hidden_access_is_fresh(CHAT_PIN_VERIFICATION_WINDOW_MINUTES)


class ChatPrivacyStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        security = _get_user_security(request.user)
        return Response({
            "has_pin": security.has_chat_pin,
            "hidden_verified": _is_hidden_access_verified(security),
            "hidden_verified_at": security.hidden_pin_verified_at,
            "updated_at": security.updated_at,
        }, status=status.HTTP_200_OK)


class ChatPrivacyPinView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        security = _get_user_security(request.user)
        current_pin = (request.data.get("current_pin") or "").strip()
        new_pin = (request.data.get("new_pin") or "").strip()
        confirm_pin = (request.data.get("confirm_pin") or "").strip()
        remove_pin = bool(request.data.get("remove_pin"))

        if security.has_chat_pin:
            if not current_pin:
                return Response({"error": "Debes ingresar tu PIN actual"}, status=status.HTTP_400_BAD_REQUEST)
            if not security.verify_chat_pin(current_pin):
                return Response({"error": "PIN actual incorrecto"}, status=status.HTTP_400_BAD_REQUEST)

        if remove_pin:
            security.clear_chat_pin()
            _reset_pin_rate_limit(request.user)
            return Response({"message": "PIN de chats desactivado"}, status=status.HTTP_200_OK)

        if not new_pin or len(new_pin) != 6 or not new_pin.isdigit():
            return Response({"error": "El PIN debe tener exactamente 6 dígitos"}, status=status.HTTP_400_BAD_REQUEST)

        if not confirm_pin or new_pin != confirm_pin:
            return Response({"error": "Los PIN no coinciden"}, status=status.HTTP_400_BAD_REQUEST)

        security.set_chat_pin(new_pin)
        _reset_pin_rate_limit(request.user)

        return Response({
            "message": "PIN de chats actualizado correctamente",
            "has_pin": True,
        }, status=status.HTTP_200_OK)


class VerifyChatPinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        security = _get_user_security(request.user)
        pin = (request.data.get("pin") or "").strip()
        token = (request.data.get("access_token") or request.data.get("token") or "").strip()

        if security.has_chat_pin and pin:
            if not security.verify_chat_pin(pin):
                if _register_failed_pin_attempt(request.user):
                    return Response(
                        {"error": "Has superado el límite de intentos. Inténtalo más tarde."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )
                return Response({"error": "PIN incorrecto"}, status=status.HTTP_400_BAD_REQUEST)

            security.mark_hidden_verified()
            _reset_pin_rate_limit(request.user)
            access_payload = f"{request.user.id}:{security.updated_at.isoformat()}"
            signed_token = _chat_pin_signer.sign(access_payload)
            return Response({
                "message": "PIN verificado correctamente",
                "access_token": signed_token,
                "verified_until": (timezone.now() + timedelta(minutes=CHAT_PIN_VERIFICATION_WINDOW_MINUTES)).isoformat(),
            }, status=status.HTTP_200_OK)

        if token:
            try:
                payload = _chat_pin_signer.unsign(token, max_age=CHAT_PIN_VERIFICATION_WINDOW_MINUTES * 60)
                user_id, token_version = payload.split(":", 1)
                if str(request.user.id) != user_id:
                    raise BadSignature("Token does not belong to current user")
                if token_version != _get_user_security(request.user).updated_at.isoformat():
                    raise BadSignature("Token does not belong to current user")
                security.mark_hidden_verified()
                return Response({
                    "message": "Acceso temporal restaurado",
                    "access_token": token,
                    "verified_until": (timezone.now() + timedelta(minutes=CHAT_PIN_VERIFICATION_WINDOW_MINUTES)).isoformat(),
                }, status=status.HTTP_200_OK)
            except (BadSignature, SignatureExpired):
                return Response({"error": "El acceso temporal expiró"}, status=status.HTTP_401_UNAUTHORIZED)

        return Response({"error": "Debes configurar un PIN antes de acceder a ocultos"}, status=status.HTTP_400_BAD_REQUEST)
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECONDS = 15 * 60   # 15 minutos


def _login_rate_key(email: str) -> str:
    return f"login-attempts:{email.lower()}"


def _check_login_rate(email: str):
    """Devuelve (blocked: bool, attempts: int)."""
    key = _login_rate_key(email)
    attempts = cache.get(key, 0)
    return attempts >= _LOGIN_MAX_ATTEMPTS, attempts


def _record_login_failure(email: str):
    key = _login_rate_key(email)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, timeout=_LOGIN_WINDOW_SECONDS)


def _reset_login_rate(email: str):
    cache.delete(_login_rate_key(email))


class LoginView(APIView):
    def post(self, request):
        email = request.data.get('email', '').strip()
        password = request.data.get('password', '')

        # Rate limiting — bloquear después de 10 intentos fallidos en 15 min
        blocked, attempts = _check_login_rate(email)
        if blocked:
            return Response(
                {"error": "Demasiados intentos fallidos. Espera 15 minutos e inténtalo de nuevo."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = User.objects.filter(email=email).first()
        if not user:
            _record_login_failure(email)
            return Response({"error": "Credenciales inválidas"}, status=status.HTTP_401_UNAUTHORIZED)
        if user.check_password(password):
            _reset_login_rate(email)
            redis_client = get_redis_client()
            refresh = RefreshToken.for_user(user)
            seen_key = f"seen:{user.id}"
            seen_videos = redis_client.smembers(seen_key)
            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "has_seen_videos": bool(seen_videos),
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "profile_picture": _abs_media(user.profile_picture.url if user.profile_picture else None) or settings.BACKEND_URL.rstrip('/') + '/media/profile_pics/avatar.webp',
                    "is_buzzy_premium": getattr(user, 'buzzy_premium', None) is not None and user.buzzy_premium.is_active,
                    "phone_number": user.phone_number,
                    "onboarding_completed": user.onboarding_completed,
                }
            }, status=status.HTTP_200_OK)
        else:
            _record_login_failure(email)
            return Response({"error": "Credenciales inválidas"}, status=status.HTTP_401_UNAUTHORIZED)
   
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]  # Solo usuarios autenticados pueden hacer logout

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")  # Obtener el refresh token del request
            token = RefreshToken(refresh_token)
            token.blacklist()  # Invalidar el token agregándolo a la lista negra

            return Response({"message": "Logout exitoso"}, status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response({"error": "Token inválido o expirado"}, status=status.HTTP_400_BAD_REQUEST)
        

class GoogleLoginView(APIView):
    def post(self, request):
        access_token = request.data.get('access_token')
        photo_url = request.data.get('photo_url')  # Optional Google avatar URL
        if not access_token:
            return Response({"error": "No token provided"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            google_response = http_requests.get(
                f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}"
            )
            if not google_response.ok:
                return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)
                
            user_info = google_response.json()
            email = user_info.get("email")
            first_name = user_info.get("given_name", "")
            last_name = user_info.get("family_name", "")
            
            # Get real client IP
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR')

            # Extract country from Google's 'locale' property as fallback
            locale = user_info.get("locale", "")
            country_code = "US"
            if "-" in locale:
                country_code = locale.split("-")[1].upper()
            elif "_" in locale:
                country_code = locale.split("_")[1].upper()

            # Attempt to get precise country from IP API (overrides generic Google locale)
            try:
                import requests
                # If local development, force "DO" for the user testing from Dominican Republic
                if ip and (ip.startswith("127.") or ip.startswith("192.168")):
                    country_code = "DO"
                else:
                    ip_response = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5)
                    if ip_response.ok:
                        ip_data = ip_response.json()
                        if ip_data.get("country_code"):
                            country_code = ip_data.get("country_code").upper()
            except Exception as e:
                print("Error getting real IP country:", e)
                
            # Use photo_url from frontend (already extracted from Firebase result.user.photoURL)
            # Fallback to Google userinfo picture field
            profile_pic_url = photo_url or user_info.get("picture")
            
            # Only allow existing registered users to log in with Google
            user = User.objects.filter(email=email).first()
            if not user:
                return Response(
                    {
                        "error": "not_registered",
                        "message": "No tienes una cuenta en Buzzy. Por favor regístrate primero.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            is_new_user = False
            if not user.country:
                # If existing user somehow has no country, try to assign one
                from apps.users.models import Country
                country_obj, _ = Country.objects.get_or_create(code=country_code, defaults={'name': country_code})
                user.country = country_obj
                user.save()

            # Save Google photo if user has no profile picture (new user or existing without photo)
            if profile_pic_url and not user.profile_picture:
                try:
                    from urllib.request import urlopen
                    from django.core.files.base import ContentFile
                    import os
                    img_response = urlopen(profile_pic_url)
                    img_data = img_response.read()
                    filename = f"google_{user.id}_{secrets.token_hex(4)}.jpg"
                    user.profile_picture.save(filename, ContentFile(img_data), save=True)
                except Exception as photo_err:
                    print(f"Could not save Google photo: {photo_err}")
                    
            redis_client = get_redis_client()
            seen_key = f"seen:{user.id}"
            seen_videos = redis_client.smembers(seen_key)
            refresh = RefreshToken.for_user(user)
            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "has_seen_videos": bool(seen_videos),
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "profile_picture": _abs_media(user.profile_picture.url if user.profile_picture else None) or (profile_pic_url or settings.BACKEND_URL.rstrip('/') + '/media/profile_pics/avatar.webp'),
                    "country": getattr(user.country, 'code', None),
                    "is_buzzy_premium": getattr(user, 'buzzy_premium', None) is not None and user.buzzy_premium.is_active,
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _build_unique_username(base_value: str) -> str:
    from .models import User

    slug = re.sub(r"[^a-zA-Z0-9._]", "", (base_value or "").strip().lower())
    slug = slug.strip("._") or "user"
    candidate = slug[:150]
    suffix = 0

    while User.objects.filter(username=candidate).exists():
        suffix += 1
        suffix_token = f"_{suffix}"
        candidate = f"{slug[: max(1, 150 - len(suffix_token))]}{suffix_token}"

    return candidate


class GoogleRegisterView(APIView):
    def post(self, request):
        access_token = request.data.get("access_token")
        photo_url = request.data.get("photo_url")
        country_code = (request.data.get("country_code") or "US").upper()
        country_name = request.data.get("country_name") or "United States"
        referral_code = (request.data.get("referral_code") or "").strip()

        if not access_token:
            return Response({"error": "No token provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            google_response = http_requests.get(
                f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}"
            )
            if not google_response.ok:
                return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)

            user_info = google_response.json()
            email = user_info.get("email")
            first_name = user_info.get("given_name", "")
            last_name = user_info.get("family_name", "")
            profile_pic_url = photo_url or user_info.get("picture")

            if not email:
                return Response({"error": "Google account missing email"}, status=status.HTTP_400_BAD_REQUEST)

            if User.objects.filter(email=email).exists():
                return Response(
                    {
                        "error": "already_registered",
                        "message": "Ya tienes una cuenta en Buzzy. Inicia sesión con Google.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            username_base = user_info.get("email", "").split("@")[0] or f"{first_name}{last_name}" or "user"
            username = _build_unique_username(username_base)

            user = User.objects.create_user(
                email=email,
                username=username,
                password=None,
                first_name=first_name,
                last_name=last_name,
            )
            user.set_unusable_password()

            from apps.users.models import Country
            country_obj, _ = Country.objects.get_or_create(code=country_code, defaults={"name": country_name})
            user.country = country_obj

            if profile_pic_url:
                try:
                    from urllib.request import urlopen
                    from django.core.files.base import ContentFile

                    img_response = urlopen(profile_pic_url)
                    img_data = img_response.read()
                    filename = f"google_{user.id}_{secrets.token_hex(4)}.jpg"
                    user.profile_picture.save(filename, ContentFile(img_data), save=False)
                except Exception as photo_err:
                    print(f"Could not save Google photo on register: {photo_err}")

            user.save()

            # --- Lógica de Referidos (igual que en registro normal) ---
            if referral_code:
                try:
                    from apps.referrals.models import ReferralToken, ReferralProfile
                    with transaction.atomic():
                        ref_token = (
                            ReferralToken.objects
                            .select_for_update()
                            .filter(token=referral_code, is_active=True)
                            .first()
                        )
                        # Bloqueo 1: auto-referido
                        # Bloqueo 2: lazo cerrado
                        closed_loop = ref_token and ReferralToken.objects.filter(
                            owner=user, used_by=ref_token.owner
                        ).exists()

                        # Bloqueo 3: ya se benefició de un referido antes
                        already_benefited = ReferralToken.objects.filter(used_by=user).exists()

                        if (
                            ref_token
                            and not closed_loop
                            and not already_benefited
                            and ref_token.expires_at > timezone.now()
                            and ref_token.owner_id != user.id
                        ):
                            ref_token.is_active = False
                            ref_token.used_by = user
                            ref_token.save(update_fields=['is_active', 'used_by'])

                            invitee_wallet = WalletModel.objects.select_for_update().filter(
                                user=user, wallet_type='main'
                            ).first()
                            if invitee_wallet:
                                invitee_wallet.tokens += 100
                                invitee_wallet.save(update_fields=['tokens'])

                            owner_profile, _ = ReferralProfile.objects.select_for_update().get_or_create(user=ref_token.owner)
                            prev_count = owner_profile.total_invitados
                            owner_profile.total_invitados = prev_count + 1
                            owner_profile.save(update_fields=['total_invitados'])

                            # Solo dispara el hito si ESTE incremento cruzó el múltiplo de 5
                            if (prev_count + 1) % 5 == 0:
                                owner_wallet = WalletModel.objects.select_for_update().filter(
                                    user=ref_token.owner, wallet_type='main'
                                ).first()
                                if owner_wallet:
                                    owner_wallet.tokens += 100
                                    owner_wallet.save(update_fields=['tokens'])
                except Exception:
                    pass  # No bloquear el registro si el referido falla

            redis_client = get_redis_client()
            seen_key = f"seen:{user.id}"
            seen_videos = redis_client.smembers(seen_key)
            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user": {
                        "has_seen_videos": bool(seen_videos),
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "profile_picture": _abs_media(user.profile_picture.url if user.profile_picture else None) or (profile_pic_url or settings.BACKEND_URL.rstrip("/") + "/media/profile_pics/avatar.webp"),
                        "country": getattr(user.country, "code", None),
                    },
                },
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




class RegisterView(APIView):
    def post(self, request):
        from django.db import transaction

        # Rate limiting: máximo 5 intentos de registro por IP en 10 minutos
        ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()
        rate_key = f"register_attempts:{ip}"
        attempts = cache.get(rate_key, 0)
        if attempts >= 5:
            return Response(
                {"error": "Demasiados intentos. Espera unos minutos antes de intentarlo de nuevo."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        cache.set(rate_key, attempts + 1, timeout=600)

        name = request.data.get('name')
        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')
        confirm_password = request.data.get('repeat_password')
        country_name = request.data.get('country')
        country_code = request.data.get('country_code', 'US')
        phone_number = request.data.get('phone_number')
        referral_code = (request.data.get('referral_code') or '').strip()

        # País obligatorio
        if not country_name or not country_code:
            return Response(
                {"error": "El país es obligatorio para registrarse."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validar que las contraseñas coincidan
        if password != confirm_password:
            return Response({
            "error": "Las contraseñas no coinciden."
        }, status=status.HTTP_404_NOT_FOUND)

        # Validar que el nombre de usuario no esté ya en uso
        if User.objects.filter(username=username).exists():
            return Response({
            "error": "El username ya está en uso"
        }, status=status.HTTP_404_NOT_FOUND)

        # Validar que el correo electrónico no esté ya en uso
        if User.objects.filter(email=email).exists():
            return Response({
            "error": "El correo electrónico ya está en uso"
        }, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            # Crear el usuario
            user = User.objects.create_user(email=email, username=username, password=password, first_name=name)

            if phone_number:
                user.phone_number = phone_number
                user.is_phone_verified = False  # se confirma solo vía /api/auth/verify-phone/

            if country_name:
                from apps.users.models import Country
                country_obj, _ = Country.objects.get_or_create(code=country_code, defaults={'name': country_name})
                user.country = country_obj

            user.save()

            # Guardar el código de referido para procesarlo SOLO cuando el teléfono sea verificado con Firebase
            # Esto evita que alguien reciba tokens sin verificación real de identidad
            if referral_code:
                user.pending_referral_code = referral_code
                user.save(update_fields=['pending_referral_code'])

        # Generar JWT
        refresh = RefreshToken.for_user(user)

        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "profile_picture": _abs_media(user.profile_picture.url if user.profile_picture else None) or settings.BACKEND_URL.rstrip('/') + '/media/profile_pics/avatar.webp',
            },
        }, status=status.HTTP_201_CREATED)
    
class DetaildUser(APIView):
    serializer_class = DetailedUserSerializer
    permission_classes = [IsAuthenticated]
    def get(self, request, username, *args, **kwargs):
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            try:
                user = User.objects.get(is_owner=True)
            except User.DoesNotExist:
                return Response({"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        serialised_user = self.serializer_class(user, context={'request': request})

        chat_room = ChatRoom.objects.filter(
            participant1=user,
            participant2=request.user
        )

        user_data = serialised_user.data
        user_data["chat_uuid"] = chat_room[0].uuid if chat_room.exists() else ""

        # Notify profile owner (skip if viewing own profile)
        if user != request.user:
            create_and_broadcast_notification(
                recipient=user,
                actor=request.user,
                notification_type=Notification.Type.PROFILE_VISIT,
            )

        return Response({
            "user": user_data
        }, status=status.HTTP_200_OK)
    

class MediaByUser(APIView):
    serializer_class =  VideoZerializer
    # authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            try:
                user = User.objects.get(is_owner=True)
            except User.DoesNotExist:
                return Response({"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        media = Video.objects.filter(user_id=user)
        serialised_user = self.serializer_class(media, many=True, context={'request': request})
        return Response({
            "media_user":  serialised_user.data,
        }, status=status.HTTP_200_OK)


class SaveAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        user = request.user
        start_time = request.data.get('start_time') # "08:00"
        end_time = request.data.get('end_time')     # "20:00"
        days = request.data.get('days')             # [0, 2, 4] (Lunes, Miércoles, Viernes)

        # 1. Opcional: Limpiar disponibilidades previas para este usuario 
        # (si quieres que el modal reemplace lo anterior)
        Availability.objects.filter(user=user).delete()

        # 2. Crear un registro por cada día seleccionado
        new_availabilities = []
        for day_index in days:
            new_availabilities.append(
                Availability(
                    user=user,
                    day_of_week=day_index,
                    start_time=start_time,
                    end_time=end_time
                )
            )
        
        # bulk_create guarda todo en una sola consulta a la DB (muy eficiente)
        Availability.objects.bulk_create(new_availabilities)
        return Response({"message": "Horario guardado con éxito"}, status=201)


class GetAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        availabilities = Availability.objects.filter(user=request.user, is_active=True).order_by('day_of_week')
        data = [
            {
                "day_of_week": a.day_of_week,
                "start_time": a.start_time.strftime("%H:%M"),
                "end_time": a.end_time.strftime("%H:%M"),
                "is_active": a.is_active,
            }
            for a in availabilities
        ]
        return Response(data, status=200)


# ─── Social OAuth ───────────────────────────────────────────────────────────────

def get_social_session():
    """Retorna una sesión con reintentos configurados para mayor estabilidad."""
    session = http_requests.Session()
    retry_strategy = Retry(
        total=3,  # Reintentar hasta 3 veces
        backoff_factor=1,  # Esperar 1s, 2s, 4s...
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

OAUTH_CONFIGS = {
   "instagram": {
    "auth_url": "https://www.facebook.com/v19.0/dialog/oauth",
    "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
    "profile_url": "https://graph.facebook.com/me",
    "client_id_key": "FACEBOOK_APP_ID",
    "client_secret_key": "FACEBOOK_APP_SECRET",
    "scope": "public_profile,pages_show_list,pages_read_engagement,instagram_basic",
},
    "tiktok": {
        "auth_url": "https://www.tiktok.com/v2/auth/authorize",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "profile_url": "https://open.tiktokapis.com/v2/user/info/",
        "client_id_key": "TIKTOK_CLIENT_KEY",
        "client_secret_key": "TIKTOK_CLIENT_SECRET",
        "scope": "user.info.basic,user.info.profile,user.info.stats",
        "profile_fields": "open_id,display_name,username,follower_count",
    },
    "facebook": {
        "auth_url": "https://www.facebook.com/v19.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
        "profile_url": "https://graph.facebook.com/me",
        "client_id_key": "FACEBOOK_APP_ID",
        "client_secret_key": "FACEBOOK_APP_SECRET",
        "scope": "public_profile,pages_show_list,instagram_basic,pages_read_engagement,instagram_manage_insights",
        "profile_fields": "id,name,friends.summary(true)",
    },
}


class SocialOAuthInitView(APIView):
    """Genera la URL de autorización de OAuth y la devuelve al frontend."""
    permission_classes = [IsAuthenticated]

    def get(self, request, platform):
        config = OAUTH_CONFIGS.get(platform)
        if not config:
            return Response({"error": "Plataforma no soportada"}, status=400)

        client_id = getattr(settings, config["client_id_key"], None)
        if not client_id:
            return Response(
                {"error": f"Credenciales de {platform} no configuradas en el servidor."},
                status=503,
            )

        state = secrets.token_urlsafe(32)
        request.session[f"oauth_state_{platform}"] = state

        redirect_uri = f"{settings.FRONTEND_URL}/social/callback/{platform}".rstrip('/')

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": config["scope"],
            "response_type": "code",
            "state": state,
        }

        # TikTok requiere PKCE (code_verifier + code_challenge)
        if platform == "tiktok":
            import hashlib, base64
            params["client_key"] = params.pop("client_id")
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).rstrip(b"=").decode()
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
            # Guardar verifier para usarlo en el callback
            request.session["tiktok_code_verifier"] = code_verifier

        auth_url = config["auth_url"] + "?" + urlencode(params)
        return Response({"url": auth_url}, status=200)


class SocialOAuthCallbackView(APIView):
    """Recibe el código OAuth, lo intercambia por un token y guarda la cuenta."""
    permission_classes = [IsAuthenticated]

    def get(self, request, platform):
        config = OAUTH_CONFIGS.get(platform)
        if not config:
            return Response({"error": "Plataforma no soportada"}, status=400)

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            return Response({"error": f"OAuth denegado: {error}"}, status=400)

        if not code:
            return Response({"error": "Código de autorización faltante"}, status=400)

        # Validar state (protección CSRF)
        expected_state = request.session.get(f"oauth_state_{platform}")
        if expected_state and state != expected_state:
            return Response({"error": "State inválido. Posible ataque CSRF."}, status=400)

        client_id = getattr(settings, config["client_id_key"], "")
        client_secret = getattr(settings, config["client_secret_key"], "")
        redirect_uri = f"{settings.FRONTEND_URL}/social/callback/{platform}".rstrip('/')
        session = get_social_session()  # Asumiendo que tienes esta función definida

        # 1. Intercambiar código por access_token
        try:
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
            }

            if platform == "tiktok":
                token_data["client_key"] = token_data.pop("client_id")
                code_verifier = request.session.get("tiktok_code_verifier", "")
                if code_verifier:
                    token_data["code_verifier"] = code_verifier

            token_resp = session.post(
                config["token_url"],
                data=token_data,
                timeout=20,
            )

            if not token_resp.ok:
                try:
                    error_detail = token_resp.json()
                    return Response(
                        {"error": f"Error obteniendo token ({platform}): {error_detail}"},
                        status=token_resp.status_code
                    )
                except:
                    return Response(
                        {"error": f"Error {token_resp.status_code}: {token_resp.text}"},
                        status=400
                    )

            token_json = token_resp.json()
            access_token = token_json.get("access_token")
            refresh_token = token_json.get("refresh_token", "")

        except Exception as e:
            return Response({"error": f"Error al conectar con la plataforma: {str(e)}"}, status=502)

        # 2. Intercambio por token long-lived (solo Facebook/Instagram)
        if platform in ("instagram", "facebook") and access_token:
            try:
                exchange_params = {
                    "grant_type": "fb_exchange_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "fb_exchange_token": access_token
                }
                exchange_resp = session.get(
                    config["token_url"],
                    params=exchange_params,
                    timeout=20
                )
                if exchange_resp.ok:
                    exchange_json = exchange_resp.json()
                    access_token = exchange_json.get("access_token", access_token)
                    # refresh_token queda vacío (Facebook no lo usa)
            except Exception:
                pass  # Si falla, usamos el token corto (puede ser suficiente para pruebas)

        # 3. Obtener datos del perfil según la plataforma
        try:
            if platform == "instagram":
                # ────────────────────────────────────────────────
                # Flujo CORRECTO para Instagram Graph API (2025-2026)
                # ────────────────────────────────────────────────

                # 3.1 Obtener páginas de Facebook que administra el usuario
                pages_resp = session.get(
                    "https://graph.facebook.com/v20.0/me/accounts",  # ← Actualiza a la versión más reciente
                    params={"access_token": access_token},
                    timeout=20,
                )
                pages_data = pages_resp.json()

                if "data" not in pages_data or not pages_data["data"]:
                    return Response(
                        {"error": "No se encontraron páginas de Facebook que administres. Necesitas vincular tu Instagram profesional a una Página de Facebook que administres."},
                        status=400
                    )

                # Por ahora tomamos la primera página (en producción: permitir selección)
                page = pages_data["data"][0]
                page_id = page["id"]
                page_access_token = page["access_token"]  # ← ¡Este es el token clave para Instagram!

                # 3.2 Obtener la cuenta de Instagram Business/Creator vinculada a esa página
                ig_account_resp = session.get(
                    f"https://graph.facebook.com/v20.0/{page_id}",
                    params={
                        "fields": "instagram_business_account",
                        "access_token": page_access_token,
                    },
                    timeout=20,
                )
                ig_account_data = ig_account_resp.json()

                ig_account = ig_account_data.get("instagram_business_account")
                if not ig_account or "id" not in ig_account:
                    return Response(
                        {
                            "error": (
                                "La página seleccionada no tiene una cuenta profesional de Instagram vinculada.\n\n"
                                "Pasos para solucionar:\n"
                                "1. Abre Instagram → Configuración → Cuenta → Cambiar a cuenta profesional\n"
                                "2. Vincula tu cuenta a una Página de Facebook que administres\n"
                                "3. Asegúrate de aceptar todos los permisos solicitados"
                            )
                        },
                        status=400
                    )

                ig_user_id = ig_account["id"]

                # 3.3 Obtener datos del perfil de Instagram
                profile_resp = session.get(
                    f"https://graph.facebook.com/v20.0/{ig_user_id}",
                    params={
                        "fields": "id,username,followers_count,profile_picture_url,biography,name,website",
                        "access_token": page_access_token,
                    },
                    timeout=20,
                )
                profile_json = profile_resp.json()

                if "error" in profile_json:
                    return Response(
                        {"error": f"Error al obtener datos de Instagram: {profile_json['error'].get('message', 'Desconocido')}"},
                        status=400
                    )

                # Campos normalizados
                platform_user_id = str(profile_json.get("id", ""))
                platform_username = profile_json.get("username", "Sin username")
                platform_followers = profile_json.get("followers_count", 0)

                # Opcional: guardar más datos si tu modelo lo permite
                # extra_data = profile_json  # o un subconjunto

            elif platform == "tiktok":
                profile_resp = session.get(
                    config["profile_url"],
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"fields": "open_id,display_name,username,follower_count"},
                    timeout=20,
                )
                profile_resp.raise_for_status()
                profile_json = profile_resp.json()

                tiktok_data = profile_json.get("data", {}).get("user", {})
                platform_user_id = str(tiktok_data.get("open_id", ""))
                platform_username = tiktok_data.get("display_name") or tiktok_data.get("username", "")
                platform_followers = tiktok_data.get("follower_count", 0)

            else:  # facebook
                # Obtener páginas del usuario con su fan_count
                pages_resp = session.get(
                    "https://graph.facebook.com/v19.0/me/accounts",
                    params={"access_token": access_token, "fields": "id,name,access_token,fan_count"},
                    timeout=20,
                )
                pages_json = pages_resp.json()
                pages = pages_json.get("data", [])

                if pages:
                    page = pages[0]
                    page_id = page["id"]
                    page_name = page.get("name", "")
                    page_access_token = page.get("access_token", access_token)
                    platform_followers = page.get("fan_count", 0)

                    if platform_followers == 0:
                        page_resp = session.get(
                            f"https://graph.facebook.com/v19.0/{page_id}",
                            params={"fields": "id,name,fan_count,followers_count", "access_token": page_access_token},
                            timeout=20,
                        )
                        page_data = page_resp.json()
                        platform_followers = page_data.get("fan_count") or page_data.get("followers_count", 0)
                        platform_username = page_data.get("name", page_name)
                        platform_user_id = str(page_data.get("id", page_id))
                    else:
                        platform_username = page_name
                        platform_user_id = str(page_id)
                else:
                    # App en modo Development — me/accounts no devuelve páginas
                    # Guardar el perfil personal, fan_count llegará al publicar la app
                    me_resp = session.get(
                        "https://graph.facebook.com/v19.0/me",
                        params={"fields": "id,name", "access_token": access_token},
                        timeout=20,
                    )
                    me_json = me_resp.json()
                    platform_user_id = str(me_json.get("id", ""))
                    platform_username = me_json.get("name", "User")
                    platform_followers = 0

        except Exception as e:
            return Response({"error": f"Error al obtener perfil: {str(e)}"}, status=502)

        # 4. Guardar/actualizar la cuenta social
        social_account, created = SocialAccount.objects.update_or_create(
            user=request.user,
            platform=platform,
            defaults={
                "platform_user_id": platform_user_id,
                "platform_username": platform_username,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "followers_count": platform_followers,
                # Opcional: "extra_data": profile_json,   # si quieres guardar más info
            },
        )

        return Response(
            {
                "message": f"{platform.capitalize()} conectado correctamente",
                "platform": platform,
                "platform_username": platform_username,
                "connected": True,
            },
            status=200,
        )

class SocialAccountStatusView(APIView):
    """Lista las cuentas sociales conectadas del usuario."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = SocialAccount.objects.filter(user=request.user)
        serializer = SocialAccountSerializer(accounts, many=True)
        return Response(serializer.data, status=200)


class SocialAccountDisconnectView(APIView):
    """Desconecta (elimina) la cuenta social de una plataforma."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, platform):
        deleted, _ = SocialAccount.objects.filter(
            user=request.user, platform=platform
        ).delete()
        if deleted:
            return Response({"message": f"{platform.capitalize()} desconectado"}, status=200)
        return Response({"error": "Cuenta no encontrada"}, status=404)

class SocialAccountRefreshView(APIView):
    """Refresca el followers_count de todas las redes sociales conectadas del usuario."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        accounts = SocialAccount.objects.filter(user=request.user)
        if not accounts.exists():
            return Response({"message": "No hay cuentas conectadas"}, status=200)

        http_session = get_social_session()
        updated = []

        for account in accounts:
            try:
                if account.platform == "facebook":
                    pages_resp = http_session.get(
                        "https://graph.facebook.com/v19.0/me/accounts",
                        params={
                            "access_token": account.access_token,
                            "fields": "id,name,fan_count,access_token",
                        },
                        timeout=15,
                    )
                    pages = pages_resp.json().get("data", [])
                    if pages:
                        page = pages[0]
                        page_access_token = page.get("access_token", account.access_token)
                        fan_count = page.get("fan_count", 0)
                        if fan_count == 0:
                            page_resp = http_session.get(
                                f"https://graph.facebook.com/v19.0/{page['id']}",
                                params={"fields": "fan_count,followers_count", "access_token": page_access_token},
                                timeout=15,
                            )
                            page_data = page_resp.json()
                            fan_count = page_data.get("fan_count") or page_data.get("followers_count", 0)
                        account.followers_count = fan_count
                        account.save(update_fields=["followers_count"])
                        updated.append({"platform": "facebook", "followers_count": fan_count})

                elif account.platform == "instagram":
                    # Instagram: usar el page access token guardado para pedir followers_count
                    pages_resp = http_session.get(
                        "https://graph.facebook.com/v20.0/me/accounts",
                        params={"access_token": account.access_token},
                        timeout=15,
                    )
                    pages = pages_resp.json().get("data", [])
                    if pages:
                        page_access_token = pages[0].get("access_token", account.access_token)
                        ig_resp = http_session.get(
                            f"https://graph.facebook.com/v20.0/{account.platform_user_id}",
                            params={"fields": "followers_count", "access_token": page_access_token},
                            timeout=15,
                        )
                        ig_data = ig_resp.json()
                        followers = ig_data.get("followers_count", account.followers_count)
                        account.followers_count = followers
                        account.save(update_fields=["followers_count"])
                        updated.append({"platform": "instagram", "followers_count": followers})

                elif account.platform == "tiktok":
                    profile_resp = http_session.post(
                        "https://open.tiktokapis.com/v2/user/info/",
                        headers={"Authorization": f"Bearer {account.access_token}", "Content-Type": "application/json"},
                        json={"fields": ["follower_count"]},
                        timeout=15,
                    )
                    tiktok_data = profile_resp.json().get("data", {}).get("user", {})
                    followers = tiktok_data.get("follower_count", account.followers_count)
                    account.followers_count = followers
                    account.save(update_fields=["followers_count"])
                    updated.append({"platform": "tiktok", "followers_count": followers})

            except Exception:
                # Si falla el refresh de una plataforma, continúa con las demás
                continue

        return Response({"updated": updated}, status=200)


class UpdateProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        user = request.user
        data = request.data

        # Validar username si está cambiando
        new_username = data.get('username')
        if new_username and new_username != user.username:
            if User.objects.filter(username=new_username).exists():
                return Response({"error": "Este nombre de usuario ya está en uso"}, status=status.HTTP_400_BAD_REQUEST)
            user.username = new_username

        # Actualizar otros campos
        user.first_name = data.get('first_name', user.first_name)
        user.last_name = data.get('last_name', user.last_name)
        user.bio = data.get('bio', user.bio)

        # Actualizar teléfono — recompensa de onboarding solo una vez en el backend
        phone_number = data.get('phone_number')
        if phone_number and not user.onboarding_completed:
            user.phone_number = phone_number
            user.onboarding_completed = True
            try:
                from apps.wallet.models import WalletModel
                wallet = WalletModel.objects.get(user=user)
                if wallet.tokens == 0:
                    wallet.tokens = 100
                    wallet.save(update_fields=['tokens'])
            except Exception as e:
                print(f"Error giving onboarding token reward: {e}")
            try:
                from apps.videos.models import Notification
                from apps.videos.views import create_and_broadcast_notification
                buzzy_actor = User.objects.filter(is_owner=True).first() or user
                create_and_broadcast_notification(
                    recipient=user,
                    actor=buzzy_actor,
                    notification_type=Notification.Type.WELCOME,
                    message="🎉 ¡Bienvenido a Buzzy! Nos alegra tenerte aquí. Explora, conecta y comparte.",
                )
            except Exception as e:
                print(f"Error sending welcome notification: {e}")
            try:
                from apps.banners.models import BuzzyBanner
                BuzzyBanner.objects.create(
                    user=user,
                    title="¡Bienvenido a Buzzy! 🎉",
                    message="Nos alegra tenerte aquí. Explora, conecta y comparte con la comunidad.",
                    type="ACHIEVEMENT",
                    effect="PARTICLES",
                    target="PERSONAL",
                    background_color="#7C3AED",
                    text_color="#FFFFFF",
                    accent_color="#00f0ff",
                )
            except Exception as e:
                print(f"Error creating welcome banner: {e}")
        elif phone_number:
            user.phone_number = phone_number

        # Actualizar país
        country_name = data.get('country')
        country_code = data.get('country_code')
        if country_name and country_code:
            from apps.users.models import Country
            country_obj, _ = Country.objects.get_or_create(code=country_code, defaults={'name': country_name})
            user.country = country_obj

        # Manejar imagen de perfil
        profile_picture = request.FILES.get('profile_picture')
        if profile_picture:
            user.profile_picture = profile_picture

        # Manejar video de perfil (máximo 3 segundos)
        profile_video = request.FILES.get('profile_video')
        if profile_video:
            # En un entorno real, usaríamos cv2 o moviepy para validar la duración.
            # Por ahora, confiaremos en la validación del frontend o asumiremos que el backend procesará esto.
            # Sin embargo, como regla de negocio, lo guardamos.
            user.profile_video = profile_video

        try:
            user.save()
            return Response({
                "message": "Perfil actualizado correctamente",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "bio": user.bio,
                    "profile_picture": _abs_media(user.profile_picture.url if user.profile_picture else None) or None,
                    "profile_video": _abs_media(user.profile_video.url if user.profile_video else None),
                    "phone_number": user.phone_number,
                    "onboarding_completed": user.onboarding_completed,
                    "country": user.country.name if user.country else None,
                    "country_code": user.country.code if user.country else None,
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Error al guardar el perfil: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

class UserAvailabilityStatusView(APIView):
    """
    Checks if a target user is currently available and if the requesting user
    can make calls (voice/video) based on their subscription plan.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        try:
            try:
                target_user = User.objects.get(username=username)
            except User.DoesNotExist:
                target_user = User.objects.get(is_owner=True)
            requesting_user = request.user

            # 1. Check if target_user is available NOW using the same exact logic used everywhere else
            is_available = target_user.is_currently_available()
            
            # 2. Check the active subscription between requester and target user
            subscription = UserSubscription.objects.filter(
                subscriber=requesting_user,
                subscribed_to=target_user,
                is_active=True
            ).select_related('plan').first()
            
            can_voice = False
            can_video = False
            remaining_calls = 0
            remaining_video_calls = 0
            remaining_voice_seconds = 0
            remaining_video_seconds = 0
            plan_name = "NONE"
            upgrade_required = False

            if subscription and subscription.is_active and subscription.plan:
                plan_name = subscription.plan.name
                subscription.reset_if_new_month()
                can_voice_by_limit, _ = subscription.can_make_call()
                can_video_by_limit, _ = subscription.can_make_video_call()

                voice_limit = subscription.get_benefit_limit('CALLS')
                video_limit = subscription.get_benefit_limit('VIDEO CALLS')
                remaining_voice_seconds = subscription.get_remaining_seconds('CALLS')
                remaining_video_seconds = subscription.get_remaining_seconds('VIDEO CALLS')

                can_voice = can_voice_by_limit
                can_video = can_video_by_limit

                if voice_limit > 0:
                    remaining_calls = max(0, voice_limit - int(subscription.voice_seconds_this_month / 60))
                if video_limit > 0:
                    remaining_video_calls = max(0, video_limit - int(subscription.video_seconds_consumed_this_month / 60))

                upgrade_required = not can_voice and not can_video

            return Response({
                "username": username,
                "is_available": is_available,
                "can_voice": can_voice,
                "can_video": can_video,
                "remaining_calls": remaining_calls,
                "remaining_video_calls": remaining_video_calls,
                "remaining_voice_seconds": remaining_voice_seconds,
                "remaining_video_seconds": remaining_video_seconds,
                "plan_name": plan_name,
                "upgrade_required": upgrade_required
            }, status=200)

        except User.DoesNotExist:
            return Response({"error": "Usuario no encontrado"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class ForgotPasswordView(APIView):
    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "El correo es requerido"}, status=400)
        
        try:
            user = User.objects.get(email=email)
            code = generate_reset_code()
            user.reset_password_code = code
            user.reset_password_expires = timezone.now() + timedelta(minutes=10)
            user.save()
            
            if send_recovery_email(email, code):
                return Response({"message": "Código de recuperación enviado"}, status=200)
            else:
                return Response({"error": "Error enviando el correo"}, status=500)
        except User.DoesNotExist:
            return Response({"error": "No existe un usuario con ese correo"}, status=404)

class VerifyCodeView(APIView):
    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')
        
        if not email or not code:
            return Response({"error": "Correo y código requeridos"}, status=400)
        
        try:
            user = User.objects.get(email=email, reset_password_code=code)
            if user.reset_password_expires < timezone.now():
                return Response({"error": "El código ha expirado"}, status=400)
            
            return Response({"message": "Código verificado correctamente"}, status=200)
        except User.DoesNotExist:
            return Response({"error": "Código inválido"}, status=400)

class PasswordResetView(APIView):
    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')
        password = request.data.get('password')
        confirm_password = request.data.get('confirm_password')
        
        if not all([email, code, password, confirm_password]):
            return Response({"error": "Todos los campos son requeridos"}, status=400)
        
        if password != confirm_password:
            return Response({"error": "Las contraseñas no coinciden"}, status=400)
            
        try:
            user = User.objects.get(email=email, reset_password_code=code)
            if user.reset_password_expires < timezone.now():
                return Response({"error": "El código ha expirado"}, status=400)
            
            user.set_password(password)
            user.reset_password_code = None
            user.reset_password_expires = None
            user.save()
            
            return Response({"message": "Contraseña actualizada correctamente"}, status=200)
        except User.DoesNotExist:
            return Response({"error": "Sesión de recuperación inválida"}, status=400)



class LanguageUpdateView(APIView):
    """
    GET  api/user/language/ — return current user's language preference
    PATCH api/user/language/ — update user's language preference
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"language": request.user.language})

    def patch(self, request):
        language = request.data.get("language")
        valid = [code for code, _ in request.user.LANGUAGE_CHOICES]
        if not language or language not in valid:
            return Response(
                {"error": f"Invalid language. Supported: {valid}"},
                status=400,
            )
        request.user.language = language
        request.user.save(update_fields=["language"])
        return Response({"language": language})


class VerifyPhoneView(APIView):
    """
    Verifica el número de teléfono del usuario usando el ID token de Firebase.

    POST /api/auth/verify-phone/
    Body: { "firebase_token": "<idToken>", "phone_number": "<+1234567890>" }

    Reglas de negocio:
    - Si sms_blocked_until está en el futuro → rechazar (bloqueo de 24h).
    - Si sms_attempts >= 5 → bloquear 24 horas y rechazar.
    - El token de Firebase se verifica con Firebase Admin SDK.
    - El phone_number del token Firebase debe coincidir con el enviado.
    - Un número solo puede existir en una cuenta (unicidad en BD).
    - Al verificar correctamente: is_phone_verified=True, sms_attempts=0, onboarding_completed=True.
    """
    permission_classes = [IsAuthenticated]

    MAX_ATTEMPTS = 5
    BLOCK_HOURS = 24

    def post(self, request):
        firebase_token = request.data.get("firebase_token", "").strip()
        phone_number = request.data.get("phone_number", "").strip()

        if not firebase_token or not phone_number:
            return Response(
                {"error": "Se requieren firebase_token y phone_number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        now = timezone.now()

        # Verificar si el usuario está bloqueado por exceso de intentos
        if user.sms_blocked_until and user.sms_blocked_until > now:
            remaining = user.sms_blocked_until - now
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return Response(
                {
                    "error": f"Demasiados intentos. Intenta de nuevo en {hours}h {minutes}m.",
                    "blocked": True,
                    "blocked_until": user.sms_blocked_until.isoformat(),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Verificar que el número no esté ya en uso por otra cuenta
        if User.objects.filter(phone_number=phone_number).exclude(pk=user.pk).exists():
            return Response(
                {"error": "Este número de teléfono ya está registrado en otra cuenta."},
                status=status.HTTP_409_CONFLICT,
            )

        # Verificar el token con Firebase Admin SDK
        try:
            import firebase_admin
            from firebase_admin import auth as firebase_auth

            # Inicializar la app de Firebase Admin si no está inicializada
            try:
                firebase_admin.get_app()
            except ValueError:
                from pathlib import Path
                cred_path = Path(__file__).resolve().parent.parent.parent / "buzzy-app-8086f-firebase-adminsdk-fbsvc-2772bee6a1.json"
                cred = firebase_admin.credentials.Certificate(str(cred_path))
                firebase_admin.initialize_app(cred)

            decoded_token = firebase_auth.verify_id_token(firebase_token)
            token_phone = decoded_token.get("phone_number", "")

            if token_phone != phone_number:
                return Response(
                    {"error": "El número no coincide con el token de Firebase."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception:
            # Contar intento fallido
            user.sms_attempts += 1
            if user.sms_attempts >= self.MAX_ATTEMPTS:
                user.sms_blocked_until = now + timedelta(hours=self.BLOCK_HOURS)
                user.sms_attempts = 0
                user.save(update_fields=["sms_attempts", "sms_blocked_until"])
                return Response(
                    {
                        "error": f"Demasiados intentos fallidos. Bloqueado por {self.BLOCK_HOURS} horas.",
                        "blocked": True,
                        "blocked_until": user.sms_blocked_until.isoformat(),
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            user.save(update_fields=["sms_attempts"])
            return Response(
                {
                    "error": "Código inválido o expirado. Intenta de nuevo.",
                    "attempts_left": self.MAX_ATTEMPTS - user.sms_attempts,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificación exitosa
        user.phone_number = phone_number
        user.is_phone_verified = True
        user.sms_attempts = 0
        user.sms_blocked_until = None
        user.onboarding_completed = True
        user.save(update_fields=[
            "phone_number",
            "is_phone_verified",
            "sms_attempts",
            "sms_blocked_until",
            "onboarding_completed",
        ])

        # Procesar referido pendiente ahora que la identidad está verificada con Firebase
        referral_code = user.pending_referral_code
        referral_applied = False
        referral_code_used = False

        if referral_code:
            try:
                from django.db import transaction
                from apps.referrals.models import ReferralToken, ReferralProfile
                from apps.wallet.models import WalletModel

                with transaction.atomic():
                    ref_token = (
                        ReferralToken.objects
                        .select_for_update()
                        .filter(token=referral_code, is_active=True)
                        .first()
                    )

                    # Token inactivo = ya fue usado por alguien más
                    if not ref_token:
                        referral_code_used = True

                    closed_loop = ref_token and ReferralToken.objects.filter(
                        owner=user, used_by=ref_token.owner
                    ).exists()

                    already_benefited = ReferralToken.objects.filter(used_by=user).exists()

                    if (
                        ref_token
                        and not closed_loop
                        and not already_benefited
                        and ref_token.expires_at > timezone.now()
                        and ref_token.owner_id != user.id
                    ):
                        ref_token.is_active = False
                        ref_token.used_by = user
                        ref_token.save(update_fields=['is_active', 'used_by'])

                        invitee_wallet = WalletModel.objects.select_for_update().filter(
                            user=user, wallet_type='main'
                        ).first()
                        if invitee_wallet:
                            invitee_wallet.tokens += 100
                            invitee_wallet.save(update_fields=['tokens'])

                        owner_profile, _ = ReferralProfile.objects.select_for_update().get_or_create(user=ref_token.owner)
                        prev_count = owner_profile.total_invitados
                        owner_profile.total_invitados = prev_count + 1
                        owner_profile.save(update_fields=['total_invitados'])

                        if (prev_count + 1) % 5 == 0:
                            owner_wallet = WalletModel.objects.select_for_update().filter(
                                user=ref_token.owner, wallet_type='main'
                            ).first()
                            if owner_wallet:
                                owner_wallet.tokens += 100
                                owner_wallet.save(update_fields=['tokens'])

                        referral_applied = True
                    elif ref_token:
                        # Token existe pero fue bloqueado por alguna regla de seguridad
                        referral_code_used = True

                # Limpiar el código pendiente independientemente del resultado
                user.pending_referral_code = None
                user.save(update_fields=['pending_referral_code'])

            except Exception:
                pass  # El referido nunca bloquea la verificación

        return Response(
            {
                "success": True,
                "message": "Número de teléfono verificado correctamente.",
                "referral_applied": referral_applied,
                "referral_code_used": referral_code_used,
            },
            status=status.HTTP_200_OK,
        )


class RegisterDeviceView(APIView):
    """Registers or refreshes an FCM device token for the authenticated user."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.users.models import FCMDevice
        token = request.data.get("token", "").strip()
        if not token:
            return Response({"error": "token es requerido"}, status=status.HTTP_400_BAD_REQUEST)

        # Upsert: if the token already exists update its owner, otherwise create it
        device, created = FCMDevice.objects.update_or_create(
            token=token,
            defaults={"user": request.user},
        )
        return Response(
            {"registered": True, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
