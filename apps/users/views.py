import uuid
import secrets
from datetime import datetime, timedelta
from django.utils import timezone
from .utils import generate_reset_code, send_recovery_email
import requests as http_requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlencode
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.wallet.models import WalletModel
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status
from apps.videos.serializers import  VideoZerializer
from apps.videos.models import Video
from .models import Availability, User, SocialAccount
from .serializers import DetailedUserSerializer, SocialAccountSerializer
from apps.videos.models import ChatRoom
from apps.subscriptions.models import UserSubscription
class LoginView(APIView):
    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "Credenciales inválidas"}, status=status.HTTP_401_UNAUTHORIZED)
        if self.request.user and user.check_password(password):
            refresh = RefreshToken.for_user(user)
            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                       "profile_picture": user.profile_picture.url if user.profile_picture else 'http://localhost:8000/media/profile_pics/avatar.webp',
                }
            }, status=status.HTTP_200_OK)
        else:
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
            
            # Find or create user
            user = User.objects.filter(email=email).first()
            is_new_user = False
            if not user:
                is_new_user = True
                base_username = email.split('@')[0]
                username = f"{base_username}_{secrets.token_hex(4)}"
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    password=secrets.token_urlsafe(16)
                )
                
                # Assign Country from Google's locale
                from apps.users.models import Country
                country_obj, _ = Country.objects.get_or_create(code=country_code, defaults={'name': country_code})
                user.country = country_obj
                user.save()


            elif not user.country:
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

            refresh = RefreshToken.for_user(user)
            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "profile_picture": user.profile_picture.url if user.profile_picture else (profile_pic_url or 'http://localhost:8000/media/profile_pics/avatar.webp'),
                    "country": getattr(user.country, 'code', None)
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




class RegisterView(APIView):
    def post(self, request):

        name = request.data.get('name')
        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')
        confirm_password = request.data.get('repeat_password')
        country_name = request.data.get('country')
        country_code = request.data.get('country_code', 'US')
        phone_number = request.data.get('phone_number')

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

        # Crear el usuario
        user = User.objects.create_user(email=email, username=username, password=password,  first_name=name)
        
        if phone_number:
            user.phone_number = phone_number
            user.is_phone_verified = True  # Valido por Firebase antes de llamar a esta API
            
        if country_name:
            from apps.users.models import Country
            country_obj, _ = Country.objects.get_or_create(code=country_code, defaults={'name': country_name})
            user.country = country_obj
            
        user.save()

        # Generar tokens
        refresh = RefreshToken.for_user(user)

        #create a wallet

        # Retornar los tokens y los datos del usuario
        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "profile_picture": user.profile_picture.url if user.profile_picture else 'http://localhost:8000/media/profile_pics/avatar.webp',
            },
        }, status=status.HTTP_201_CREATED)
    
class DetaildUser(APIView):
    serializer_class = DetailedUserSerializer
    permission_classes = [IsAuthenticated]
    def get(self, request, username, *args, **kwargs):
        user = User.objects.get(username=username)
        serialised_user = self.serializer_class(user, context={'request': request})

        chat_room = ChatRoom.objects.filter(
            participant1=user,
            participant2=request.user
        )


        user_data = serialised_user.data
        user_data["chat_uuid"] = chat_room[0].uuid if chat_room.exists() else ""

        return Response({
            "user": user_data
        }, status=status.HTTP_200_OK)
    

class MediaByUser(APIView):
    serializer_class =  VideoZerializer
    # authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        user = User.objects.get(username=username)
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
        "scope": "user.info.basic",
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
        # Guardar state en sesión para validar en el callback (CSRF protection)
        request.session[f"oauth_state_{platform}"] = state

        redirect_uri = f"{settings.FRONTEND_URL}/social/callback/{platform}".rstrip('/')

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": config["scope"],
            "response_type": "code",
            "state": state,
        }
        # TikTok usa `client_key` en lugar de `client_id`
        if platform == "tiktok":
            params["client_key"] = params.pop("client_id")

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
                profile_resp = session.post(
                    config["profile_url"],
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"fields": ["open_id", "display_name", "username", "follower_count"]},
                    timeout=20,
                )
                profile_resp.raise_for_status()
                profile_json = profile_resp.json()

                tiktok_data = profile_json.get("data", {}).get("user", {})
                platform_user_id = str(tiktok_data.get("open_id", ""))
                platform_username = tiktok_data.get("display_name") or tiktok_data.get("username", "")
                platform_followers = tiktok_data.get("follower_count", 0)

            else:  # facebook
                profile_resp = session.get(
                    config["profile_url"],
                    params={"fields": config.get("profile_fields", "id,name"), "access_token": access_token},
                    timeout=20,
                )
                profile_resp.raise_for_status()
                profile_json = profile_resp.json()

                platform_user_id = str(profile_json.get("id", ""))
                platform_username = profile_json.get("name") or profile_json.get("username", "User")
                # Si tienes user_friends → puedes obtener conteo de amigos
                friends = profile_json.get("friends", {}).get("summary", {})
                platform_followers = friends.get("total_count", 0)

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
                    "profile_picture": user.profile_picture.url if user.profile_picture else None,
                    "profile_video": user.profile_video.url if user.profile_video else None,
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
            target_user = User.objects.get(username=username)
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
