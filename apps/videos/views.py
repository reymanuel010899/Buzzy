import json
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import get_object_or_404
import requests
from django.conf import settings
from apps.subscriptions.models import UserSubscription
from apps.subscriptions.utils import send_push_notification
from apps.recommendations.services import record_video_view, update_user_interests
from django.utils import timezone
from datetime import timedelta
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Exists, OuterRef
from django.db import ProgrammingError
# from apps.wallet.models import WalletModel
from .models import AudioTrack, ChatRoom, Comment, FavoriteTrack, Follower, GiftStory, Like, Message, MessageReaction, Notification, SavedVideo, Story, StoryGift, StoryLike, StoryMedia, StoryReport, StoryView, UserGift, UserOnlineStatus, Video, VideoGift, VideoStats, View, User
from .serializers import AudioTrackSerializer, ChatRoomSerializer, FavoriteTrackSerializer, FollowerListSerializer, CommentSerializers, FollowerSerializer, GetGiftStorySerializer, GiftRecivedSerializer, GiftStorySerializer, LikeSerializers, ListCommentsZerializers, MessageSerializer, NotificationSerializer, StoryLikeSerializer, StorySerializer, StoryViewSerializer, UserSerializers, VideoZerializer, ViewSerializers, formated_created
from apps.wallet.models import WalletModel, GlobalSettings
from apps.wallet.serializers import WalletSerializer
from django.core.cache import cache
from collections import Counter
from django.db.models import F
from django.db.models.functions import Extract
from rest_framework.parsers import MultiPartParser, FormParser
from .tasks import process_video_ai


def _abs(path):
    """Convert relative media path to absolute URL using BACKEND_URL."""
    if not path:
        return None
    if str(path).startswith("http"):
        return str(path)
    base = settings.BACKEND_URL.rstrip("/")
    s = str(path)
    return f"{base}{s}" if s.startswith("/") else f"{base}/{s}"


def _ws_headers() -> dict:
    """Return auth headers for internal Django → FastAPI broadcast calls."""
    return {"X-Broadcast-Secret": settings.BROADCAST_SECRET}


class UpdateDeviceTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('device_token')
        if not token:
            return Response({'error': 'device_token results is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        status_obj, created = UserOnlineStatus.objects.get_or_create(user=request.user)
        status_obj.device_token = token
        status_obj.save()
        
        return Response({'message': 'Token updated successfully'})

# Create your views here.
FASTAPI_WS_URL = "http://localhost:8001"
HIDDEN_CHAT_TOKEN_SALT = "buzzy-hidden-chat-pin"
HIDDEN_CHAT_TOKEN_WINDOW_SECONDS = 5 * 60


def _hidden_pin_signer() -> TimestampSigner:
    return TimestampSigner(salt=HIDDEN_CHAT_TOKEN_SALT)


def _get_user_security(user: User):
    security = getattr(user, "security", None)
    if security is None:
        from apps.users.models import UserSecurity
        security, _ = UserSecurity.objects.get_or_create(user=user)
    return security


def _is_mutual_follow(user_a, user_b) -> bool:
    return (
        Follower.objects.filter(user_id=user_a, follower_user_id=user_b).exists()
        and Follower.objects.filter(user_id=user_b, follower_user_id=user_a).exists()
    )


def _resolve_folder_type(chat: ChatRoom, viewer: User) -> str:
    """
    Retorna el folder donde el viewer ve este chat.
    Cada participante tiene su propio folder independiente.

    - HIDDEN  → el viewer lo marcó como oculto
    - KNOWN   → el viewer lo movió manualmente a conocidos
    - REQUEST → el otro inició el chat y el viewer nunca ha respondido
    - STANDARD → follow mutuo, o el viewer ya respondió
    """
    personal = chat.get_folder_for(viewer)

    if personal == ChatRoom.FolderType.HIDDEN:
        return ChatRoom.FolderType.HIDDEN

    if personal == ChatRoom.FolderType.KNOWN:
        return ChatRoom.FolderType.KNOWN

    other_user = chat.get_other_participant(viewer)
    if _is_mutual_follow(viewer, other_user):
        return ChatRoom.FolderType.STANDARD

    # Si el viewer nunca ha enviado un mensaje → solicitud para él
    viewer_has_replied = Message.objects.filter(
        chat_room=chat, sender=viewer
    ).exists()
    if not viewer_has_replied:
        return ChatRoom.FolderType.REQUEST

    return ChatRoom.FolderType.STANDARD


def _ensure_hidden_access(request):
    security = _get_user_security(request.user)
    if security.hidden_access_is_fresh():
        return None

    access_token = (
        request.query_params.get("access_token")
        or request.query_params.get("pin_token")
        or request.headers.get("X-Chat-Pin-Token")
    )

    if access_token:
        try:
            payload = _hidden_pin_signer().unsign(access_token, max_age=HIDDEN_CHAT_TOKEN_WINDOW_SECONDS)
            user_id, token_version = payload.split(":", 1)
            current_version = security.updated_at.isoformat()
            if user_id != str(request.user.id) or token_version != current_version:
                raise BadSignature("Token mismatch")
            security.mark_hidden_verified()
            return None
        except (BadSignature, SignatureExpired):
            pass

    return Response(
        {"error": "Necesitas verificar tu PIN de chats para ver ocultos"},
        status=status.HTTP_403_FORBIDDEN,
    )

class ListMediaApiView(ListAPIView):
    """
    Endpoint de inicio para usuarios nuevos sin historial.
    Devuelve 20 videos populares con diversidad de categorías (máx 3 por categoría).
    Una vez que el usuario acumula interacciones, el frontend debe migrar a /feed/.
    """
    serializer_class = VideoZerializer

    def get_queryset(self):
        from apps.recommendations.views import _cold_start_videos
        # Feed público (sin auth): solo videos públicos
        return _cold_start_videos(seen_ids=[], limit=10, user=None)

class VideoDetailApiView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uuid):
        try:
            video = Video.objects.get(uuid=uuid, status="ready")
        except Video.DoesNotExist:
            return Response({"error": "Video no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        serializer = VideoZerializer(video, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, uuid):
        try:
            video = Video.objects.get(uuid=uuid, user_id=request.user)
        except Video.DoesNotExist:
            return Response({"error": "Video no encontrado o no tienes permiso."}, status=status.HTTP_404_NOT_FOUND)
        video.delete()
        return Response({"success": True}, status=status.HTTP_200_OK)


class UserVideosApiView(ListAPIView):
    """
    Devuelve hasta `limit` videos públicos de un usuario (por username),
    excluyendo los IDs que el frontend ya tiene.
    GET /api/videos/user/<username>/?exclude=1,2,3&limit=5
    """
    permission_classes = [IsAuthenticated]
    serializer_class = VideoZerializer

    def get_queryset(self):
        username = self.kwargs.get("username")
        exclude_param = self.request.query_params.get("exclude", "")
        limit = min(int(self.request.query_params.get("limit", 5)), 20)

        try:
            exclude_ids = [int(i) for i in exclude_param.split(",") if i.strip().isdigit()]
        except ValueError:
            exclude_ids = []

        from django.db.models import Q
        viewer = self.request.user
        target_qs = Video.objects.filter(user_id__username=username, status="ready")

        if viewer.is_authenticated and viewer.username == username:
            # El propio autor ve todos sus videos
            pass
        elif viewer.is_authenticated:
            from apps.videos.models import Follower as FollowerModel
            i_follow = FollowerModel.objects.filter(
                user_id=viewer
            ).values_list('follower_user_id_id', flat=True)
            followers_of_me = FollowerModel.objects.filter(
                follower_user_id=viewer
            ).values_list('user_id_id', flat=True)
            mutual_ids = set(i_follow) & set(followers_of_me)
            target_qs = target_qs.filter(
                Q(privacy='public') |
                Q(privacy='followers', user_id__in=mutual_ids)
            )
        else:
            target_qs = target_qs.filter(privacy='public')

        return target_qs.exclude(id__in=exclude_ids).order_by("-created_at")[:limit]


class UserVideosBatchApiView(APIView):
    """
    Prefetch de videos por lote de usuarios.
    POST /api/videos/user/prefetch/
    body: { users: [{username, exclude_id}], limit: 2 }
    response: { username: [videos], ... }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        users = request.data.get("users", [])
        limit = min(int(request.data.get("limit", 2)), 10)
        result = {}
        for entry in users:
            username = entry.get("username")
            exclude_id = entry.get("exclude_id")
            if not username:
                continue
            qs = (
                Video.objects.filter(user_id__username=username, status="ready")
                .exclude(id=exclude_id)
                .order_by("-created_at")[:limit]
            )
            serializer = VideoZerializer(qs, many=True, context={"request": request})
            result[username] = serializer.data
        return Response(result, status=status.HTTP_200_OK)


class CreateViewApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ViewSerializers
    def post(self, request, *args, **kwargs):
        video_id = request.data.get("video_id")
        try:
            video = Video.objects.get(id=video_id)
            # Aquí puedes implementar la lógica para registrar la vista
            existing = View.objects.filter(user_id=request.user, video_id=video).first()
            if existing:
                return Response(
                    {"message": "La vista ya ha sido registrada anteriormente"},
                    status=status.HTTP_200_OK
                )
            View.objects.create(user_id=request.user, video_id=video)
            
            ws_data = {
                "event": "new_view",
                "video_id": video.id,
                "view_acount": video.get_count_view(),
                "user_id": request.user.id,
                "video_user_id": video.user_id.id,
                # "liked": liked
            }
            try:
                requests.post(f"{settings.FASTAPI_WS_URL}/create-view/", json=ws_data, headers=_ws_headers())
            except Exception as e:
                print("Error enviando evento WS:", e)

            record_video_view(request.user.id, video.id)
            if video.category_id:
                update_user_interests(request.user.id, video.category.id, 'view')
            return Response(
                {"message": "Vista registrada correctamente"},
                status=status.HTTP_201_CREATED
            )
        except Video.DoesNotExist:
            return Response(
                {"error": "Video no encontrado"},
                status=status.HTTP_404_NOT_FOUND
            )


class VideoEventView(APIView):
    """
    Tracks multi-stage video engagement events.
    Accepted event_types:
      video_start | video_engagement | video_view_valid | video_view_monetizable

    Rules:
      - video_view_valid       → user reached 50% of the video (any length)
      - video_view_monetizable → same trigger, but only when 50% >= 10 s
                                 (videos shorter than 20 s are not monetizable)
      - Creator watching their own video never generates a monetizable view.
      - video_view_valid:       1 hour cooldown via View table
      - video_view_monetizable: 1 per user per video per day via MonetizableViewLog
    """
    permission_classes = [IsAuthenticated]

    VALID_EVENTS = {'video_start', 'video_engagement', 'video_view_valid', 'video_view_monetizable'}
    COUNTER_MAP = {
        'video_start': 'starts',
        'video_engagement': 'engagements',
        'video_view_valid': 'valid_views',
        'video_view_monetizable': 'monetizable_views',
    }

    def post(self, request, *args, **kwargs):
        from apps.wallet.models import MonetizableViewLog

        video_id = request.data.get('video_id')
        event_type = request.data.get('event_type')

        if not video_id or event_type not in self.VALID_EVENTS:
            return Response(
                {'error': 'video_id y event_type válido son requeridos.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            video = Video.objects.get(id=video_id)
        except Video.DoesNotExist:
            return Response({'error': 'Video no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        # --- video_view_valid: 1 hora cooldown vía tabla View ---
        if event_type == 'video_view_valid':
            cutoff = timezone.now() - timedelta(hours=1)
            already_viewed = View.objects.filter(
                user_id=request.user,
                video_id=video,
                created_at__gte=cutoff
            ).exists()
            if already_viewed:
                return Response({'message': 'Vista ya registrada en la última hora.'}, status=status.HTTP_200_OK)

            view_obj, created = View.objects.get_or_create(
                user_id=request.user,
                video_id=video
            )
            if created:
                ws_data = {
                    'event': 'new_view',
                    'video_id': video.id,
                    'view_acount': video.get_count_view(),
                    'user_id': request.user.id,
                    'video_user_id': video.user_id.id,
                }
                try:
                    requests.post(f"{settings.FASTAPI_WS_URL}/create-view/", json=ws_data, headers=_ws_headers(), timeout=2)
                except Exception as e:
                    print('Error enviando evento WS (VideoEventView):', e)

        # --- video_view_monetizable: 1 por usuario por video por día + no auto-vista ---
        elif event_type == 'video_view_monetizable':
            if video.user_id == request.user:
                return Response({'message': 'Auto-vista ignorada.'}, status=status.HTTP_200_OK)

            today = timezone.now().date()
            _, log_created = MonetizableViewLog.objects.get_or_create(
                user=request.user,
                video=video,
                date=today,
            )
            if not log_created:
                return Response({'message': 'Vista monetizable ya registrada hoy.'}, status=status.HTTP_200_OK)

        # --- Atomically increment the matching counter in VideoStats ---
        counter_field = self.COUNTER_MAP[event_type]
        stats, _ = VideoStats.objects.get_or_create(video=video)
        VideoStats.objects.filter(pk=stats.pk).update(
            **{counter_field: F(counter_field) + 1}
        )

        return Response({'message': f'Evento {event_type} registrado.'}, status=status.HTTP_200_OK)


class CreateCommentApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializers

    def post(self, request, *args, **kwargs):
        video_id = request.data.get("video_id")
        if not video_id:
            return Response({"error": "video_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        video = get_object_or_404(Video, id=video_id)
        video_owner = video.user_id
        
        # Check subscription limits for this relationship
        subscription = None
        priority_comment_enabled = False
        priority_plan_name = None
        try:
            subscription = UserSubscription.objects.get(
                subscriber=request.user, 
                subscribed_to=video_owner,
                is_active=True
            )
            can_comment, message = subscription.can_post_comment()
            if can_comment:
                priority_comment_enabled = True
                priority_plan_name = subscription.plan.name if subscription.plan else None
        except UserSubscription.DoesNotExist:
            # If no 1-to-1 subscription exists, handle based on business rules
            # For now, we'll allow it if they are the owner, otherwise we follow existing logic
            if video_owner != request.user:
                # If you want to enforce subscription for comments, do it here.
                # For now, we'll keep it permissive if no record exists, matching previous behavior
                pass
        except Exception as e:
            print(f"Error checking comment subscription: {e}")
            pass

        validate_data = self.serializer_class(data=request.data, context={"request": request})

        if validate_data.is_valid():
            # Obtener parent si viene
            parent_uuid = request.data.get("parent_uuid", None)
            parent = None

            if parent_uuid:
                try:
                    parent = Comment.objects.filter(uuid=parent_uuid).first()
                except Comment.DoesNotExist:
                    parent = None

            # ── Anti-spam guards ──────────────────────────────────────────
            from .comment_guards import run_comment_guards, commit_comment_guards
            content = request.data.get("content", "")
            guard_error = run_comment_guards(
                user=request.user,
                video_id=video_id,
                content=content,
                is_reply=bool(parent),
            )
            if guard_error:
                return guard_error

            # Validar audio si viene
            audio_file = request.FILES.get("audio_file")
            audio_duration = None
            if audio_file:
                try:
                    audio_duration = float(request.data.get("audio_duration", 0))
                except (TypeError, ValueError):
                    audio_duration = 0
                if audio_duration > 10:
                    return Response(
                        {"error": "El audio no puede superar los 10 segundos."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                allowed_types = ["audio/webm", "audio/mp4", "audio/ogg", "audio/mpeg", "audio/wav"]
                if audio_file.content_type not in allowed_types:
                    return Response(
                        {"error": "Formato de audio no soportado."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Validar imagen si viene
            image_file = request.FILES.get("image_file")
            if image_file:
                allowed_image_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
                if image_file.content_type not in allowed_image_types:
                    return Response(
                        {"error": "Formato de imagen no soportado."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Crear el comentario
            comment = validate_data.save(
                user_id=request.user,
                is_priority_comment=priority_comment_enabled,
                priority_plan_name=priority_plan_name,
                audio_file=audio_file if audio_file else None,
                audio_duration=audio_duration,
                image_file=image_file if image_file else None,
            )
            if comment and parent:
                comment.parent = parent
                comment.save()

            # Commit guards after successful save
            commit_comment_guards(request.user, video_id, content, bool(parent))

            if subscription and priority_comment_enabled:
                subscription.comments_this_month += 1
                subscription.save()

            ws_data = {
                "event": "new_comment",
                "video_id": comment.video_id.id,
                "video_user_id": comment.video_id.user_id.id,
                "content": comment.content,
                "user_id": UserSerializers(request.user).data,
                "created_at": str(comment.created_at),
                "uuid": str(comment.uuid),
                "parent": self.serializer_class(comment.parent).data,
                "comments_count": comment.video_id.get_count_comment(),
                "is_priority_comment": comment.is_priority_comment,
                "priority_plan_name": comment.priority_plan_name,
            }

            try:
                requests.post(f"{settings.FASTAPI_WS_URL}/create-comment/", json=ws_data, headers=_ws_headers())
            except Exception as e:
                print("Error enviando evento WS:", e)

            # Notificación al dueño del video
            notif_type = Notification.Type.COMMENT_REPLY if comment.parent else Notification.Type.COMMENT
            notif_recipient = comment.parent.user_id if comment.parent else video_owner
            create_and_broadcast_notification(
                recipient=notif_recipient,
                actor=request.user,
                notification_type=notif_type,
                video=video,
                comment=comment,
            )

            # Notificaciones de mención en el comentario
            _notify_mentions(comment.content, actor=request.user, video=video, comment=comment)

            response_serializer = self.serializer_class(comment, context={"request": request})

            return Response(
                {"message": "Comentario creado correctamente", "data": response_serializer.data},
                status=status.HTTP_201_CREATED
            )

        return Response(validate_data.errors, status=status.HTTP_400_BAD_REQUEST)

class CreateLikeApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LikeSerializers

    def post(self, request, *args, **kwargs):
        validate_data = self.serializer_class(data=request.data)

        if not validate_data.is_valid():
            return Response(validate_data.errors, status=status.HTTP_400_BAD_REQUEST)

        video_id = request.data.get("video_id")
        user = request.user

        # Obtiene el video
        video = Video.objects.get(id=video_id)

        # Intenta crear el like
        like, created = Like.objects.get_or_create(
            user_id=user,
            video_id_id=video_id
        )

        if not created:
            # Si el like ya existía, se elimina (toggle)
            like.delete()
            liked = False  # el usuario YA NO lo tiene likeado
        else:
            liked = True  # el usuario AHORA sí lo likeó

        # Contador actualizado
        like_count = video.get_count_like()
        print(f"Video {video.user_id.id} tiene ahora {like_count} likes.")
        # Data para el WebSocket
        ws_data = {
            "event": "like_updated",
            "video_id": video.id,
            "likes": like_count,
            "liked": liked,
            "liked_by_target": Like.objects.filter(video_id_id=video_id, user_id=video.user_id.id).exists(),
            "user_id": user.id,
            "video_user_id": video.user_id.id
        }

        # Notificar en FastAPI
        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-like/", json=ws_data, headers=_ws_headers())
        except Exception as e:
            print("Error enviando evento WS:", e)

        # Notificación persistente al dueño del video (solo al dar like, no al quitar)
        if liked:
            create_and_broadcast_notification(
                recipient=video.user_id,
                actor=user,
                notification_type=Notification.Type.LIKE,
                video=video,
            )

        # Respuesta HTTP
        message = "Like creado correctamente" if liked else "Like eliminado correctamente"

        if video.category_id:
            update_user_interests(request.user.id, video.category.id, 'like')
        return Response(
            {"message": message, "data": ws_data},
            status=status.HTTP_201_CREATED if liked else status.HTTP_200_OK
        )


class GetCommentsApiView(APIView):
    serializer_class = ListCommentsZerializers

    def get(self, request, videoId, *args, **kwargs):
        video = Video.objects.get(uuid=videoId)
        comments = Comment.objects.filter(video_id=video).order_by('-created_at')
        if not comments.exists():
            return Response({"message": "No hay comentarios para este video."}, status=status.HTTP_200_OK)
        

        serializer = self.serializer_class(comments, many=True)
        print("Serializer data:", len(serializer.data))  # Debugging line
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class CreateFollowerApiView(APIView):
    serializer_class = FollowerSerializer
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        serialized_data = self.serializer_class(data=request.data)

        if serialized_data.is_valid():
            followed = Follower.objects.filter(
                user_id=request.user,
                follower_user_id=serialized_data.validated_data['follower_user_id']
            ).exists()

            if followed:
                Follower.objects.get(
                    user_id=request.user,
                    follower_user_id=serialized_data.validated_data['follower_user_id']
                ).delete()
                ws_data = {
                    "event": "delete_follower",
                    "current_user_followered": Follower.objects.filter(follower_user_id=serialized_data.validated_data['follower_user_id'], user_id=request.user).exists(),
                    "channel_profile": serialized_data.validated_data['follower_user_id'].id
                }
                try:
                    requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-follower/", json=ws_data, headers=_ws_headers())
                except Exception as e:
                    return Response(
                        {"message": "Error de websocket", "data": serialized_data.data},
                    )
  
                return Response(
                    {"message": "Dejado de seguir", "data": serialized_data.data},
                )

            ws_data = {
                    "event": "new_follower",
                    "current_user_followered": Follower.objects.filter(follower_user_id=serialized_data.validated_data['follower_user_id'], user_id=request.user).exists(),
                    "channel_profile": serialized_data.validated_data['follower_user_id'].id
                }
            serialized_data.save(user_id=request.user)
            try:
                requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-follower/", json=ws_data, headers=_ws_headers())
            except Exception as e:
                print("Error enviando evento WS:", e)

            # Notificación al usuario que fue seguido
            followed_user = serialized_data.validated_data['follower_user_id']
            create_and_broadcast_notification(
                recipient=followed_user,
                actor=request.user,
                notification_type=Notification.Type.FOLLOW,
            )

            chat_room = ChatRoom.objects.filter(participant1=followed_user, participant2=request.user)
            return Response(
                {"message": "Seguiendo correctamente", "data": serialized_data.data, "chat_uuid": chat_room[0].uuid if len(chat_room) > 0 else ""},
                status=status.HTTP_201_CREATED
            )

        return Response(
            {"message": "Funcionalidad de seguir usuario no implementada aún."},
            status=status.HTTP_400_BAD_REQUEST
        )
    

class FollowersListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        target_user = get_object_or_404(User, username=username)
        # People who follow target_user: follower_user_id = target_user
        followers = Follower.objects.filter(follower_user_id=target_user).select_related('user_id')
        
        serializer = FollowerListSerializer(
            followers, 
            many=True, 
            context={'request': request, 'view_target_user': target_user}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

class FollowingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        target_user = get_object_or_404(User, username=username)
        # People target_user follows: user_id = target_user
        following = Follower.objects.filter(user_id=target_user).select_related('follower_user_id')
        
        serializer = FollowerListSerializer(
            following, 
            many=True, 
            context={'request': request, 'view_target_user': target_user}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

class CreateStoryApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StorySerializer

    def post(self, request, *args, **kwargs):
        text = request.data.get("text")
        files = request.FILES.getlist("video")
        
        # Extracción de campos de audio
        audio_track_url = request.data.get("audio_track_url")
        audio_track_title = request.data.get("audio_track_title")
        audio_track_artist = request.data.get("audio_track_artist")
        audio_volume_music = request.data.get("audio_volume_music")
        audio_trim_start = request.data.get("audio_trim_start")
        audio_trim_end = request.data.get("audio_trim_end")
        filter_css = request.data.get("filter_css")
        location = request.data.get("location", "").strip() or None
        text_layers_raw = request.data.get("text_layers", "[]")
        sticker_layers_raw = request.data.get("sticker_layers", "[]")

        try:
            text_layers = json.loads(text_layers_raw) if isinstance(text_layers_raw, str) else text_layers_raw
        except json.JSONDecodeError:
            text_layers = []

        try:
            sticker_layers = json.loads(sticker_layers_raw) if isinstance(sticker_layers_raw, str) else sticker_layers_raw
        except json.JSONDecodeError:
            sticker_layers = []

        # Upload sticker image files and replace base64 src with server URLs
        sticker_files = request.FILES.getlist("sticker_files")
        if sticker_files:
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            import os
            sticker_file_map: dict[str, str] = {}
            for sf in sticker_files:
                sticker_id = sf.name.split("__")[0] if "__" in sf.name else sf.name
                ext = os.path.splitext(sf.name)[1] or ".png"
                path = default_storage.save(f"stories/stickers/{sticker_id}{ext}", ContentFile(sf.read()))
                url = request.build_absolute_uri(default_storage.url(path))
                sticker_file_map[sticker_id] = url
            # Replace blob/base64 src with uploaded URL in sticker layers
            for layer in sticker_layers:
                if layer.get("kind") in ("image", "video") and layer.get("id") in sticker_file_map:
                    layer["src"] = sticker_file_map[layer["id"]]
   
        # Primero creamos la historia
        story_kwargs = dict(
            user=request.user,
            text=text,
            audio_track_url=audio_track_url if audio_track_url else None,
            audio_track_title=audio_track_title,
            audio_track_artist=audio_track_artist,
            audio_volume_music=float(audio_volume_music) if audio_volume_music else 0.8,
            audio_trim_start=float(audio_trim_start) if audio_trim_start else 0.0,
            audio_trim_end=float(audio_trim_end) if audio_trim_end else None,
            filter_css=filter_css if filter_css else None,
            text_layers=text_layers if isinstance(text_layers, list) else [],
            sticker_layers=sticker_layers if isinstance(sticker_layers, list) else [],
            location=location,
        )

        used_legacy_story_schema = False
        try:
            story = Story.objects.create(**story_kwargs)
        except ProgrammingError:
            used_legacy_story_schema = True
            legacy_kwargs = dict(story_kwargs)
            legacy_kwargs.pop("filter_css", None)
            legacy_kwargs.pop("text_layers", None)
            legacy_kwargs.pop("sticker_layers", None)
            legacy_kwargs.pop("location", None)
            story = Story.objects.create(**legacy_kwargs)
            story.filter_css = story_kwargs["filter_css"]
            story.text_layers = story_kwargs["text_layers"]
            story.sticker_layers = story_kwargs["sticker_layers"]

        # Creamos los archivos multimedia
        for i, file in enumerate(files):
            media_type = "image" if "image" in file.content_type else "video"
            StoryMedia.objects.create(
                story=story,
                file=file,
                type=media_type,
                order=i
            )

        # Notificaciones de mención en el texto y capas de texto de la historia
        story_text_parts = [story_kwargs.get("text") or ""]
        for layer in story_kwargs.get("text_layers") or []:
            story_text_parts.append(layer.get("text") or "")
        _notify_mentions(" ".join(story_text_parts), actor=request.user, story=story)

        serializer = self.serializer_class(story)
        serializer_data = dict(serializer.data)
        if used_legacy_story_schema:
            serializer_data["filter_css"] = story_kwargs["filter_css"]
            serializer_data["text_layers"] = story_kwargs["text_layers"]
            serializer_data["sticker_layers"] = story_kwargs["sticker_layers"]

        ws_data = {
            "event": "new_story",
            "user_id": request.user.id,
            "story_uuid": story.uuid,
            "story": serializer_data,
            "total_media": story.media.count(),
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, headers=_ws_headers())
        except:
            pass

        return Response(
            {"message": "Historia creada correctamente", "data": serializer_data},
            status=status.HTTP_201_CREATED
        )


class CreateStoryLikeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StoryLikeSerializer

    def post(self, request, *args, **kwargs):
        story_id = request.data.get("story_uuid")

        try:
            story_media = StoryMedia.objects.get(id=story_id)
        except Story.DoesNotExist:
            return Response({"error": "Historia no encontrada"}, status=404)

        # Toggle de vista (no se debe repetir)
        like, created = StoryLike.objects.get_or_create(
            user=request.user,
            story=story_media.story
        )

        if not created:
            like.delete()
            return Response({"message": "like eliminado"}, status=200)

        # Evento WebSocket
        ws_data = {
            "event": "story_liked",
            "story_uuid": story_id,
            "total_views": story_media.story.total_views(),
            "viewer_user": request.user.id
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, headers=_ws_headers())
        except:
            pass

        return Response(
            {"message": "like registrada correctamente", "data": self.serializer_class(like).data},
            status=201
        )
    

class ListActiveStoriesApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StorySerializer

    def get(self, request, *args, **kwargs):
        user = request.user
        cutoff = timezone.now() - timedelta(hours=24)

        followed_user_ids = Follower.objects.filter(
            user_id=user 
        ).values_list('follower_user_id__id', flat=True)

        followed_user_ids = list(set(followed_user_ids))

        # 2. Filtrar stories: TUYA + de los que sigues
        stories = Story.objects.filter(
            Q(user_id__in=followed_user_ids) | Q(user_id=user),  # ← tú + seguidos
            is_active=True,
            created_at__gte=cutoff
        ).select_related('user') \
         .prefetch_related('media') \
         .order_by('-created_at') 

        # 3. (Opcional pero PRO) → Ordenar para que tu story siempre aparezca PRIMERO
        story_list = list(stories)

        my_stories = [s for s in story_list if s.user_id == user.id]
        others_stories = [s for s in story_list if s.user_id != user.id]
        final_stories = my_stories + others_stories
        serializer = self.serializer_class(final_stories, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class UserStoriesApiView(APIView):
    serializer_class = StorySerializer

    def get(self, request, user_id, *args, **kwargs):
        stories = list(Story.objects.filter(user_id=user_id, is_active=True).order_by("-created_at"))

        for story in stories:
            story.mark_expired()

        # Re-query to get only the ones still active (non-expired)
        story_ids = [s.id for s in stories]
        active_stories = Story.objects.filter(id__in=story_ids, is_active=True)

        serializer = self.serializer_class(active_stories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ViewStoryApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StoryViewSerializer

    def post(self, request, *args, **kwargs):
        story_id = request.data.get("story_uuid")

        try:
            story_media = StoryMedia.objects.get(id=story_id)
        except Story.DoesNotExist:
            return Response({"error": "Historia no encontrada"}, status=404)

        # Toggle de vista (no se debe repetir)
        view, created = StoryView.objects.get_or_create(
            user=request.user,
            story=story_media.story
        )

        if not created:
            return Response({"message": "La historia ya fue vista"}, status=200)

        # Evento WebSocket
        ws_data = {
            "event": "story_viewed",
            "story_uuid": story_id,
            "total_views": story_media.story.total_views(),
            "viewer_user": request.user.id
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, headers=_ws_headers())
        except:
            pass

        return Response(
            {"message": "Vista registrada correctamente", "data": self.serializer_class(view).data},
            status=201
        )

class StoryViewersApiView(APIView):
    def get(self, request, story_uuid, *args, **kwargs):
        try:
            story_media = StoryMedia.objects.get(id=story_uuid)
        except Story.DoesNotExist:
            return Response({"error": "Historia no encontrada"}, status=404)

        viewers = StoryView.objects.filter(story=story_media.story).select_related("user")
        data = [
        {
            "user_id": v.user.id,
            "username": v.user.username,
            "profile_picture": _abs(v.user.profile_picture.url if v.user.profile_picture else None),
            "viewed_at": formated_created.get_formatted_created_at(v.viewed_at),
            "user_liked": StoryLike.objects.filter(user=v.user, story=v.story).exists()

        }
        for v in viewers
    ]

        return Response(data, status=200)

class DeleteStoryApiView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, uuid, *args, **kwargs):
        try:
            story = Story.objects.get(uuid=uuid)
        except Story.DoesNotExist:
            return Response({"error": "Historia no encontrada"}, status=404)

        if story.user != request.user:
            return Response({"error": "No autorizado"}, status=403)

        story.delete()

        ws_data = {
            "event": "story_deleted",
            "story_uuid": uuid,
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, headers=_ws_headers())
        except:
            pass

        return Response({"message": "Historia eliminada"}, status=200)


class ReportStoryApiView(APIView):
    permission_classes = [IsAuthenticated]

    VALID_REASONS = {"spam", "violence", "nudity", "hate", "other"}

    def post(self, request, uuid, *args, **kwargs):
        try:
            story = Story.objects.get(uuid=uuid)
        except Story.DoesNotExist:
            return Response({"error": "Historia no encontrada"}, status=404)

        if story.user == request.user:
            return Response({"error": "No puedes reportar tu propio contenido"}, status=400)

        reason = request.data.get("reason", "")
        if reason not in self.VALID_REASONS:
            return Response({"error": "Razón de reporte inválida"}, status=400)

        description = request.data.get("description", "")

        report, created = StoryReport.objects.get_or_create(
            story=story,
            reported_by=request.user,
            defaults={"reason": reason, "description": description},
        )

        if not created:
            return Response({"message": "Ya reportaste este contenido"}, status=200)

        return Response({"message": "Gracias por tu reporte. Lo revisaremos pronto."}, status=201)


class CreateGiftStoryView(APIView):
    permission_classes = [IsAuthenticated]


    def post(self, request, *args, **kwargs):
        story_id = request.data.get("story_uuid")
        gift_type = request.data.get("gift_type")  # slug del GiftStory

        if not story_id or not gift_type:
            return Response(
                {"error": "story_uuid y gift_type son requeridos"},
                status=400
            )

        # 1. Obtener media y story
        try:
            story_media = StoryMedia.objects.select_related("story", "story__user").get(
                id=story_id
            )
        except StoryMedia.DoesNotExist:
            return Response({"error": "Story no encontrada"}, status=404)

        gift_obj = GiftStory.objects.filter(is_active=True).filter(
            Q(slug=gift_type) | Q(emoji=gift_type)
        ).first()
        if not gift_obj:
            return Response({"error": "Este regalo no existe"}, status=404)

        # Validar regalos exclusivos Premium
        if gift_obj.is_premium_exclusive:
            sender_premium = getattr(request.user, 'buzzy_premium', None)
            if not sender_premium or not sender_premium.is_active:
                return Response({"error": "Solo los usuarios Buzzy Premium pueden enviar este regalo exclusivo"}, status=403)
            receiver = story_media.story.user
            receiver_premium = getattr(receiver, 'buzzy_premium', None)
            if not receiver_premium or not receiver_premium.is_active:
                return Response({"error": "Este regalo exclusivo solo puede enviarse a usuarios Buzzy Premium"}, status=403)

        # No enviar regalo a tu propia historia (opcional)
        if story_media.story.user == request.user:
            return Response(
                {"error": "No puedes enviarte regalos a tu propia historia"},
                status=400
            )

        # 3. Validar y descontar tokens del remitente
        try:
            wallet = WalletModel.objects.get(user=request.user)
        except WalletModel.DoesNotExist:
            return Response({"error": "No tienes una wallet configurada"}, status=400)
        print(wallet.tokens, "-2-", gift_obj.token_price)
        if wallet.tokens < gift_obj.token_price:
            return Response(
                {"error": "Tokens insuficientes para enviar este regalo", "insufficient_tokens": True},
                status=400
            )

        # Descontar tokens del sender
        wallet.tokens -= int(gift_obj.token_price)
        wallet.save()

        obj, created = StoryView.objects.get_or_create(story=story_media.story, user=request.user)
        gift = StoryGift.objects.create(
            user=story_media.story.user,
            sender=request.user,
            story=story_media.story,
            gift=gift_obj,
            gift_type=gift_type
        )

        # 4. Websocket data
        ws_data = {
            "event": "gift_received",
            "story_uuid": story_id,
            "gift_uuid": gift.uuid,
            "gift_type": gift_type,
            "amount": gift_obj.token_price,
            "sender": gift.sender.username,
            "gift_video": _abs(gift_obj.video.url if gift_obj.video else None),
            "from_user": request.user.id,
            "total_gifts": story_media.story.received_gifts.count(),
            "color_premiun": gift.gift.color_premiun if gift.gift.color_premiun else "blue"
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, headers=_ws_headers(), timeout=2)
        except Exception:
            pass

        return Response(
            {
                "message": "Regalo enviado correctamente",
                "gift": {
                    "id": gift.id,
                    "gift_type": gift.gift_type,
                    "story": str(story_media.story.uuid),
                    "from": request.user.username,
                    "to": story_media.story.user.username,
                },
                "wallet": WalletSerializer(wallet).data
            },
            status=201
        )


class CreateGiftVideoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        video_id = request.data.get("video_id")
        gift_type = request.data.get("gift_type")
        vip_message = request.data.get("vip_message", "")

        if not video_id or not gift_type:
            return Response(
                {"error": "video_id y gift_type son requeridos"},
                status=400
            )

        # 1. Obtener el video
        try:
            video = Video.objects.select_related("user_id").get(id=video_id)
        except Video.DoesNotExist:
            return Response({"error": "Video no encontrado"}, status=404)

        gift_obj = GiftStory.objects.filter(is_active=True).filter(
            Q(slug=gift_type) | Q(emoji=gift_type)
        ).first()
        if not gift_obj:
            return Response({"error": "Este regalo no existe"}, status=404)

        # Validar regalos exclusivos Premium
        if gift_obj.is_premium_exclusive:
            sender_premium = getattr(request.user, 'buzzy_premium', None)
            if not sender_premium or not sender_premium.is_active:
                return Response({"error": "Solo los usuarios Buzzy Premium pueden enviar este regalo exclusivo"}, status=403)
            receiver = video.user_id
            receiver_premium = getattr(receiver, 'buzzy_premium', None)
            if not receiver_premium or not receiver_premium.is_active:
                return Response({"error": "Este regalo exclusivo solo puede enviarse a usuarios Buzzy Premium"}, status=403)

        # No enviar regalo a tu propio video
        if video.user_id == request.user:
            return Response(
                {"error": "No puedes enviarte regalos a tu propio video"},
                status=400
            )

        # 3. Validar y descontar tokens
        try:
            wallet = WalletModel.objects.get(user=request.user)
        except WalletModel.DoesNotExist:
            return Response({"error": "No tienes una wallet configurada"}, status=400)

        print(wallet.tokens, "-1-", gift_obj.token_price)
        if wallet.tokens < gift_obj.token_price:
            return Response(
                {"error": "Tokens insuficientes para enviar este regalo", "insufficient_tokens": True},
                status=400
            )

        wallet.tokens -= int(gift_obj.token_price)
        wallet.save()

        gift = VideoGift.objects.create(
            user=video.user_id,
            sender=request.user,
            video=video,
            gift=gift_obj,
            gift_type=gift_type,
            vip_message=vip_message
        )

        # 4. WebSocket notification
        ws_data = {
            "event": "video_gift_received",
            "video_id": video.id,
            "gift_uuid": gift.uuid,
            "gift_type": gift_type,
            "amount": gift_obj.token_price,
            "sender": gift.sender.username,
            "gift_video": _abs(gift_obj.video.url if gift_obj.video else None),
            "from_user": request.user.id,
            "to_user": video.user_id.id,
            "total_gifts": video.received_gifts.count(),
            "color_premiun": gift_obj.color_premiun if gift_obj.color_premiun else "blue"
        }

        try:
            import requests as http_requests
            http_requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, headers=_ws_headers(), timeout=2)
        except Exception:
            pass

        if video.category_id:
            update_user_interests(request.user.id, video.category.id, 'gift')
        return Response(
            {
                "message": "Regalo enviado correctamente",
                "gift": {
                    "id": gift.id,
                    "gift_type": gift.gift_type,
                    "video": video.id,
                    "from": request.user.username,
                    "to": video.user_id.username,
                },
                "wallet": WalletSerializer(wallet).data
            },
            status=201
        )

class ListGiftActiveApiView(APIView):
    serializer_class = GiftStorySerializer
    def get(self, request, *args, **kwargs):
        gifts = GiftStory.objects.filter(is_active=True).order_by("-created_at")
        serializer = self.serializer_class(gifts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class GetOneGiftActiveApiView(APIView):
    serializer_class = GetGiftStorySerializer
    def get(self, request, gift_uuid, story_uuid, *args, **kwargs):
        try:
            gift = StoryGift.objects.get(id=gift_uuid, is_active=True)
        except StoryMedia.DoesNotExist:
            return Response({"error": "Story no encontrada"}, status=404)
        
        ws_data = {
            "event": "gift_see",
            "story_uuid": StoryMedia.objects.get(story=gift.story, id=story_uuid).id,
            "id": gift.story.id,
            "gift_uuid": gift.uuid,
            "gift_type": gift.gift_type,
            "gift_video": _abs(gift.gift.video.url if gift.gift.video else None),
            "amount": gift.gift.token_price,
            "sender": gift.sender.username,
            "to_user": gift.story.user.id,
            "color_premiun": gift.gift.color_premiun if gift.gift.color_premiun else "blue"
            # "total_gifts": story_media.story.received_gifts.count()
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-gift-story/", json=ws_data, headers=_ws_headers())

        except Exception as e:
            print("error",e )

        serializer = self.serializer_class(gift)
        gift.is_active=False
        gift.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class ListGiftRecivedApiView(APIView):
    serializer_class = GiftRecivedSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, story_id, *args, **kwargs):
        user = request.user

        try:
            story_media = StoryMedia.objects.select_related("story", "story__user").get(
                id=story_id
            )
        except StoryMedia.DoesNotExist:
            return Response({"error": "Story no encontrada"}, status=404)
        
        cutoff = timezone.now() - timedelta(hours=12)
        gifts = StoryGift.objects.filter(user=user, story=story_media.story, is_active=True, created_at__gte=cutoff).order_by("-created_at")
        print(gifts)
        serializer = self.serializer_class(gifts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class ListGiftRecivedByUserApiView(APIView):

    serializer_class = GiftRecivedSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, story_id, *args, **kwargs):
        user = request.user

        try:
            story_media = StoryMedia.objects.select_related("story", "story__user").get(
                id=story_id
            )
        except StoryMedia.DoesNotExist:
            return Response({"error": "Story no encontrada"}, status=404)
        
        cutoff = timezone.now() - timedelta(hours=12)
        gifts = StoryGift.objects.filter(user=user, story=story_media.story, is_active=True, created_at__gte=cutoff).order_by("-created_at")
        serializer = self.serializer_class(gifts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class ListVideoGiftsReceivedView(APIView):
    """Regalos de video recibidos por el usuario autenticado (no vistos primero)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        gifts = VideoGift.objects.filter(
            user=request.user, is_active=True, is_seen=False
        ).select_related('sender', 'gift', 'video').order_by('-created_at')
        from .serializers import VideoGiftReceivedSerializer
        serializer = VideoGiftReceivedSerializer(gifts, many=True, context={'request': request})
        return Response({'gifts': serializer.data, 'unseen_count': gifts.count()})


class MarkVideoGiftsSeenView(APIView):
    """Marca regalo de video como visto, acredita tokens al receptor y lo elimina."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        uuid = request.data.get('uuid')
        if not uuid:
            return Response({'error': 'uuid requerido'}, status=400)

        gift = VideoGift.objects.filter(user=request.user, uuid=uuid, is_seen=False).first()
        if not gift:
            return Response({'status': 'ok'})

        gs = GlobalSettings.get_settings()
        fee = int(gift.gift.token_price * gs.gift_fee_pct / 100)
        receiver_tokens = int(gift.gift.token_price) - fee
        if receiver_tokens > 0:
            receiver_wallet, _ = WalletModel.objects.get_or_create(
                user=request.user, defaults={'wallet_type': 'main'}
            )
            receiver_wallet.tokens += receiver_tokens
            receiver_wallet.save()

        gift.delete()
        return Response({'status': 'ok', 'tokens_earned': receiver_tokens})


class CreateGiftUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        recipient_username = request.data.get("recipient_username")
        gift_type = request.data.get("gift_type")
        vip_message = request.data.get("vip_message", "")

        if not recipient_username or not gift_type:
            return Response({"error": "recipient_username y gift_type son requeridos"}, status=400)

        try:
            recipient = User.objects.get(username=recipient_username)
        except User.DoesNotExist:
            return Response({"error": "Usuario no encontrado"}, status=404)

        if recipient == request.user:
            return Response({"error": "No puedes enviarte regalos a ti mismo"}, status=400)

        gift_obj = GiftStory.objects.filter(is_active=True).filter(
            Q(slug=gift_type) | Q(emoji=gift_type)
        ).first()
        if not gift_obj:
            return Response({"error": "Este regalo no existe"}, status=404)

        if gift_obj.is_premium_exclusive:
            sender_premium = getattr(request.user, 'buzzy_premium', None)
            if not sender_premium or not sender_premium.is_active:
                return Response({"error": "Solo los usuarios Buzzy Premium pueden enviar este regalo exclusivo"}, status=403)
            receiver_premium = getattr(recipient, 'buzzy_premium', None)
            if not receiver_premium or not receiver_premium.is_active:
                return Response({"error": "Este regalo exclusivo solo puede enviarse a usuarios Buzzy Premium"}, status=403)

        try:
            wallet = WalletModel.objects.get(user=request.user)
        except WalletModel.DoesNotExist:
            return Response({"error": "No tienes una wallet configurada"}, status=400)

        if wallet.tokens < gift_obj.token_price:
            return Response({"error": "Tokens insuficientes para enviar este regalo", "insufficient_tokens": True}, status=400)

        wallet.tokens -= int(gift_obj.token_price)
        wallet.save()

        gift = UserGift.objects.create(
            recipient=recipient,
            sender=request.user,
            gift=gift_obj,
            gift_type=gift_type,
            vip_message=vip_message
        )

        ws_data = {
            "event": "user_gift_received",
            "gift_uuid": gift.uuid,
            "gift_type": gift_type,
            "amount": gift_obj.token_price,
            "sender": request.user.username,
            "gift_video": _abs(gift_obj.video.url if gift_obj.video else None),
            "from_user": request.user.id,
            "to_user": recipient.id,
            "color_premiun": gift_obj.color_premiun if gift_obj.color_premiun else "blue"
        }

        try:
            import requests as http_requests
            http_requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, headers=_ws_headers(), timeout=2)
        except Exception:
            pass

        return Response(
            {
                "message": "Regalo enviado correctamente",
                "gift": {
                    "uuid": gift.uuid,
                    "gift_type": gift.gift_type,
                    "from": request.user.username,
                    "to": recipient.username,
                },
                "wallet": WalletSerializer(wallet).data
            },
            status=201
        )


class ListUserGiftsReceivedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        gifts = UserGift.objects.filter(
            recipient=request.user, is_active=True, is_seen=False
        ).select_related('sender', 'gift').order_by('-created_at')
        from .serializers import UserGiftReceivedSerializer
        serializer = UserGiftReceivedSerializer(gifts, many=True, context={'request': request})
        unseen = gifts.filter(is_seen=False).count()
        return Response({'gifts': serializer.data, 'unseen_count': unseen})


class MarkUserGiftsSeenView(APIView):
    """Marca regalo de perfil como visto, acredita tokens al receptor y lo elimina."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        uuid = request.data.get('uuid')
        if not uuid:
            return Response({'error': 'uuid requerido'}, status=400)

        gift = UserGift.objects.filter(recipient=request.user, uuid=uuid, is_seen=False).first()
        if not gift:
            return Response({'status': 'ok'})

        gs = GlobalSettings.get_settings()
        fee = int(gift.gift.token_price * gs.gift_fee_pct / 100)
        receiver_tokens = int(gift.gift.token_price) - fee
        if receiver_tokens > 0:
            receiver_wallet, _ = WalletModel.objects.get_or_create(
                user=request.user, defaults={'wallet_type': 'main'}
            )
            receiver_wallet.tokens += receiver_tokens
            receiver_wallet.save()

        gift.delete()
        return Response({'status': 'ok', 'tokens_earned': receiver_tokens})


class MarkStoryGiftSeenView(APIView):
    """Marca regalo de historia como visto, acredita tokens al creador y lo elimina."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        uuid = request.data.get('uuid')
        if not uuid:
            return Response({'error': 'uuid requerido'}, status=400)

        gift = StoryGift.objects.filter(
            story__user=request.user, uuid=uuid, is_seen=False
        ).select_related('gift').first()
        if not gift:
            return Response({'status': 'ok'})

        gs = GlobalSettings.get_settings()
        fee = int(gift.gift.token_price * gs.gift_fee_pct / 100)
        receiver_tokens = int(gift.gift.token_price) - fee

        if receiver_tokens > 0:
            receiver_wallet, _ = WalletModel.objects.get_or_create(
                user=request.user, defaults={'wallet_type': 'main'}
            )
            receiver_wallet.tokens += receiver_tokens
            receiver_wallet.save()

        gift.delete()
        return Response({'status': 'ok', 'tokens_earned': receiver_tokens})


class ChatListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        folder = (request.query_params.get("folder") or ChatRoom.FolderType.STANDARD).strip().lower()

        # Subconsulta: ¿existe al menos un mensaje en este chat?
        has_messages = Message.objects.filter(chat_room=OuterRef('pk'))

        chats_qs = ChatRoom.objects.filter(
            Q(participant1=user) | Q(participant2=user)
        ).annotate(
            has_msg=Exists(has_messages)
        ).filter(
            # Reglas de visibilidad:
            Q(initiator=user)           # Yo inicié → siempre veo el chat (aunque no haya mensajes)
            | Q(has_msg=True)           # Hay mensajes → ambos lo vemos
        ).select_related(
            'participant1', 'participant2', 'initiator'
        ).order_by('-updated_at')

        if folder == ChatRoom.FolderType.HIDDEN:
            hidden_access_error = _ensure_hidden_access(request)
            if hidden_access_error is not None:
                return hidden_access_error
            chats = [
                chat for chat in chats_qs
                if _resolve_folder_type(chat, user) == ChatRoom.FolderType.HIDDEN
            ]
        elif folder == ChatRoom.FolderType.REQUEST:
            chats = [
                chat for chat in chats_qs
                if _resolve_folder_type(chat, user) == ChatRoom.FolderType.REQUEST
            ]
        elif folder == ChatRoom.FolderType.KNOWN:
            chats = [
                chat for chat in chats_qs
                if _resolve_folder_type(chat, user) == ChatRoom.FolderType.KNOWN
            ]
        else:
            chats = [
                chat for chat in chats_qs
                if _resolve_folder_type(chat, user) == ChatRoom.FolderType.STANDARD
            ]

        serializer = ChatRoomSerializer(chats, many=True, context={'request': request})
        return Response({
            "folder": folder,
            "chats": serializer.data
        }, status=status.HTTP_200_OK)


# OBTENER MENSAJES DE UN CHAT
class ChatMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, chat_uuid):
        """Devuelve todos los mensajes de un chat específico"""
        chat = get_object_or_404(ChatRoom, uuid=chat_uuid)

        # Verificar que el usuario pertenece al chat
        if request.user not in (chat.participant1, chat.participant2):
            return Response({"error": "No tienes acceso a este chat"}, status=status.HTTP_403_FORBIDDEN)

        if chat.get_folder_for(request.user) == ChatRoom.FolderType.HIDDEN:
            hidden_access_error = _ensure_hidden_access(request)
            if hidden_access_error is not None:
                return hidden_access_error

        # Marcar mensajes como leídos
        chat.reset_unread_count(request.user)

        messages = chat.messages.filter(is_deleted=False).select_related('sender').order_by('created_at')
        serializer = MessageSerializer(messages, many=True, context={'request': request})

        return Response({
            "messages": serializer.data,
            "chat_uuid": chat.uuid,
            "other_user": ChatRoomSerializer(chat, context={'request': request}).data['other_user']
        }, status=status.HTTP_200_OK)


# ENVIAR MENSAJE NUEVO
class SendMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Body esperado:
        {
            "recipient_id": 5,                    # ID del otro usuario
            "content": "Hola! ¿Cómo estás?",
            "message_type": "text" | "image" | "video" | "voice" | "gif"
        }
        """
        recipient_id = request.data.get("recipient_id")
        content = request.data.get("content", "").strip()
        message_type = request.data.get("message_type", "text")

        if not recipient_id:
            return Response({"error": "recipient_id es requerido"}, status=status.HTTP_400_BAD_REQUEST)

        if not content and message_type == "text":
            return Response({"error": "El contenido no puede estar vacío"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            recipient = User.objects.get(id=recipient_id)
        except User.DoesNotExist:
            return Response({"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        if recipient == request.user:
            return Response({"error": "No puedes enviarte mensajes a ti mismo"}, status=status.HTTP_400_BAD_REQUEST)

        # Obtener o crear la sala de chat
        if request.user.id < recipient.id:
            chat, created = ChatRoom.objects.get_or_create(
                participant1=request.user,
                participant2=recipient
            )
        else:
            chat, created = ChatRoom.objects.get_or_create(
                participant1=recipient,
                participant2=request.user
            )

        sender_folder = chat.get_folder_for(request.user)
        if sender_folder not in (ChatRoom.FolderType.HIDDEN, ChatRoom.FolderType.KNOWN):
            if _is_mutual_follow(request.user, recipient):
                # Follow mutuo → ambos pasan a standard si no lo han personalizado
                if sender_folder not in (ChatRoom.FolderType.HIDDEN, ChatRoom.FolderType.KNOWN):
                    chat.set_folder_for(request.user, ChatRoom.FolderType.STANDARD)
                recipient_folder = chat.get_folder_for(recipient)
                if recipient_folder not in (ChatRoom.FolderType.HIDDEN, ChatRoom.FolderType.KNOWN):
                    chat.set_folder_for(recipient, ChatRoom.FolderType.STANDARD)
            elif sender_folder == ChatRoom.FolderType.REQUEST:
                # El receptor de la solicitud está respondiendo → promover solo su propio folder
                other_sent_first = Message.objects.filter(
                    chat_room=chat, sender=recipient
                ).exists()
                viewer_replying = other_sent_first and not Message.objects.filter(
                    chat_room=chat, sender=request.user
                ).exists()
                if viewer_replying:
                    chat.set_folder_for(request.user, ChatRoom.FolderType.STANDARD)

        # Crear mensaje
        story_uuid = request.data.get("story_uuid", None)
        story_media_url = request.data.get("story_media_url", None)
        story_audio_url = request.data.get("story_audio_url", None)
        message = Message.objects.create(
            chat_room=chat,
            sender=request.user,
            content=content,
            message_type=message_type,
            file=request.FILES.get("file"),
            story_uuid=story_uuid,
            story_media_url=story_media_url,
            story_audio_url=story_audio_url,
        )
        # Actualizar metadata del chat
        chat.last_message_preview = content[:100] if content else "[Multimedia]"
        chat.last_message_time = message.created_at
        chat.updated_at = message.created_at

        # Incrementar contador de no leídos del destinatario
        if request.user == chat.participant1:
            chat.unread_count_p2 += 1
        else:
            chat.unread_count_p1 += 1
        chat.save()

        # Preparar datos para WebSocket
        message_data = MessageSerializer(message, context={'request': request}).data
        ws_payload = {
            "event": "send_message",
            "type": "message",
            "message": message_data,
            "chat_uuid": chat.uuid,
            "sender_id": request.user.id,
            "recipient_id": recipient.id,
            "unread_count_target": chat.unread_count_p2 if request.user == chat.participant1 else chat.unread_count_p1
        }
        print(ws_payload, "*******")
        # Enviar al FastAPI para broadcast en tiempo real
        try:
            safe_payload = json.loads(json.dumps(ws_payload, cls=DjangoJSONEncoder))
            requests.post(f"{FASTAPI_WS_URL}/broadcast-chat/", json=safe_payload, headers=_ws_headers(), timeout=3)
        except Exception as e:
            print("Error enviando mensaje al WebSocket:", e)
            # No fallar la API si el WS falla

        # Push notification so recipient sees the message when the app is closed
        try:
            preview = content[:60] if content else "📎 Multimedia"
            send_push_notification(
                user=recipient,
                title=request.user.username,
                body=preview,
                data={"type": "new_message", "chat_uuid": str(chat.uuid), "sender_id": str(request.user.id)},
            )
        except Exception as e:
            print(f"[push] message notification failed: {e}")

        return Response({
            "status": "Mensaje enviado",
            "message": message_data,
            "chat_uuid": chat.uuid
        }, status=status.HTTP_201_CREATED)



# MARCAR CHAT COMO LEÍDO 

class MarkChatAsReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_uuid):
        chat = get_object_or_404(ChatRoom, uuid=chat_uuid)

        if request.user not in (chat.participant1, chat.participant2):
            return Response({"error": "Acceso denegado"}, status=403)

        chat.reset_unread_count(request.user)

        return Response({"status": "Chat marcado como leído"})


class UpdateChatFolderView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, chat_uuid):
        chat = get_object_or_404(ChatRoom, uuid=chat_uuid)

        if request.user not in (chat.participant1, chat.participant2):
            return Response({"error": "Acceso denegado"}, status=status.HTTP_403_FORBIDDEN)

        folder_type = (request.data.get("folder_type") or "").strip().lower()
        valid_folders = {choice for choice, _ in ChatRoom.FolderType.choices}
        if folder_type not in valid_folders:
            return Response({"error": "folder_type inválido"}, status=status.HTTP_400_BAD_REQUEST)

        # Solo actualiza el folder del usuario que hace la petición
        chat.set_folder_for(request.user, folder_type)
        field = "folder_type_p1" if request.user == chat.participant1 else "folder_type_p2"
        chat.save(update_fields=[field, "updated_at"])

        return Response({
            "status": "updated",
            "chat_uuid": chat.uuid,
            "folder_type": folder_type,
        }, status=status.HTTP_200_OK)
    
class UpdateOnlineStatusView(APIView):
    permission_classes = [IsAuthenticated] 

    def post(self, request):
        user_id = request.data.get("user_id")
        is_online = request.data.get("is_online", False)
        device_token = request.data.get("device_token")

        if not user_id:
            return Response({"error": "user_id requerido"}, status=400)

        try:
            user = User.objects.get(id=user_id)
            status, created = UserOnlineStatus.objects.get_or_create(
                user=user,
                defaults={'is_online': False}
            )
            status.is_online = is_online
            if device_token:
                status.device_token = device_token
            if not is_online:
                status.last_seen = timezone.now()
            status.save()

            return Response({"status": "updated", "is_online": status.is_online})
        except User.DoesNotExist:
            return Response({"error": "Usuario no encontrado"}, status=404)
class UserConnectionsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        # Usuarios a los que sigo
        following_ids = Follower.objects.filter(user_id=user).values_list('follower_user_id', flat=True)
        # Usuarios que me siguen
        followers_ids = Follower.objects.filter(follower_user_id=user).values_list('user_id', flat=True)
        
        # Combinar IDs únicos
        connection_ids = set(list(following_ids) + list(followers_ids))
        
        # Obtener objetos User
        connections = User.objects.filter(id__in=connection_ids).distinct()
        
        serializer = UserSerializers(connections, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class DeleteMessageView(APIView):
    """Eliminar mensaje — solo para mí o para todos (estilo WhatsApp)."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, msg_uuid):
        message = get_object_or_404(Message, uuid=msg_uuid)
        chat = message.chat_room

        if request.user not in (chat.participant1, chat.participant2):
            return Response({"error": "Acceso denegado"}, status=403)

        delete_for_all = request.query_params.get("for_all", "false").lower() == "true"

        if delete_for_all:
            if message.sender != request.user:
                return Response({"error": "Solo el remitente puede eliminar para todos"}, status=403)
            message.content = "[Este mensaje fue eliminado]"
            message.deleted_for_all = True
            message.file = None
            message.save(update_fields=["content", "deleted_for_all", "file"])
            # Notificar al otro participante via WS
            other = chat.get_other_participant(request.user)
            try:
                import requests as req
                from django.conf import settings
                req.post(
                    f"{settings.FASTAPI_WS_URL}/send-to-user/",
                    json={"user_id": other.id, "data": {"event": "message_deleted", "uuid": msg_uuid, "for_all": True, "chat_uuid": chat.uuid}},
                    headers={"X-Broadcast-Secret": settings.BROADCAST_SECRET},
                    timeout=2,
                )
            except Exception:
                pass
        else:
            message.is_deleted = True
            message.save(update_fields=["is_deleted"])

        return Response({"status": "deleted", "for_all": delete_for_all})


class EditMessageView(APIView):
    """Editar el contenido de un mensaje de texto (solo el remitente, solo texto)."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, msg_uuid):
        message = get_object_or_404(Message, uuid=msg_uuid)
        if message.sender != request.user:
            return Response({"error": "Solo el remitente puede editar el mensaje"}, status=403)
        if message.message_type != 'text' or message.deleted_for_all or message.is_deleted:
            return Response({"error": "Este mensaje no se puede editar"}, status=400)
        new_content = request.data.get("content", "").strip()
        if not new_content:
            return Response({"error": "El contenido no puede estar vacío"}, status=400)
        message.content = new_content
        message.is_edited = True
        message.save(update_fields=["content", "is_edited"])
        return Response({"status": "edited", "content": new_content})


class SearchMessagesView(APIView):
    """Buscar mensajes dentro de un chat por texto."""
    permission_classes = [IsAuthenticated]

    def get(self, request, chat_uuid):
        chat = get_object_or_404(ChatRoom, uuid=chat_uuid)
        if request.user not in (chat.participant1, chat.participant2):
            return Response({"error": "Acceso denegado"}, status=403)

        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"results": []})

        messages = chat.messages.filter(
            is_deleted=False,
            deleted_for_all=False,
            content__icontains=q,
        ).select_related("sender").order_by("created_at")[:50]

        serializer = MessageSerializer(messages, many=True, context={"request": request})
        return Response({"results": serializer.data})


class ForwardMessageView(APIView):
    """Reenviar un mensaje a uno o varios chats."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        msg_uuid = request.data.get("message_uuid")
        recipient_ids = request.data.get("recipient_ids", [])

        if not msg_uuid or not recipient_ids:
            return Response({"error": "message_uuid y recipient_ids son requeridos"}, status=400)

        original = get_object_or_404(Message, uuid=msg_uuid)
        chat = original.chat_room
        if request.user not in (chat.participant1, chat.participant2):
            return Response({"error": "Acceso denegado"}, status=403)

        forwarded = []
        for rid in recipient_ids[:5]:  # max 5 destinatarios
            try:
                recipient = User.objects.get(id=rid)
            except User.DoesNotExist:
                continue

            # Get or create chat room
            target_chat = ChatRoom.objects.filter(
                participant1__in=[request.user, recipient],
                participant2__in=[request.user, recipient],
            ).first()
            if not target_chat:
                p1, p2 = (request.user, recipient) if request.user.id < recipient.id else (recipient, request.user)
                target_chat = ChatRoom.objects.create(participant1=p1, participant2=p2)

            new_msg = Message.objects.create(
                chat_room=target_chat,
                sender=request.user,
                content=original.content,
                message_type=original.message_type,
                file=original.file,
                forwarded_from=original,
            )
            target_chat.updated_at = timezone.now()
            target_chat.save(update_fields=["updated_at"])
            forwarded.append({"chat_uuid": str(target_chat.uuid), "msg_uuid": new_msg.uuid})

        return Response({"forwarded": forwarded})


class MarkMessagesReadView(APIView):
    """Marcar todos los mensajes de un chat como leídos y notificar al emisor."""
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_uuid):
        chat = get_object_or_404(ChatRoom, uuid=chat_uuid)
        if request.user not in (chat.participant1, chat.participant2):
            return Response({"error": "Acceso denegado"}, status=403)

        now = timezone.now()
        updated = chat.messages.filter(
            is_read=False,
            is_deleted=False,
        ).exclude(sender=request.user).update(is_read=True, read_at=now)

        chat.reset_unread_count(request.user)

        if updated:
            other = chat.get_other_participant(request.user)
            try:
                import requests as req
                from django.conf import settings
                req.post(
                    f"{settings.FASTAPI_WS_URL}/send-to-user/",
                    json={"user_id": other.id, "data": {"event": "messages_read", "chat_uuid": chat.uuid, "reader": request.user.username}},
                    headers={"X-Broadcast-Secret": settings.BROADCAST_SECRET},
                    timeout=2,
                )
            except Exception:
                pass

        return Response({"status": "ok", "marked": updated})


class SaveMessageReactionView(APIView):
    """
    Called internally by BuzzySocket to persist a message reaction.
    POST body: { message_uuid, user_id, emoji }
    If reaction already exists → delete it (toggle). Else → create it.
    """
    permission_classes = []  # Internal endpoint – BuzzySocket calls without user session

    def post(self, request):
        message_uuid = request.data.get("message_uuid")
        user_id = request.data.get("user_id")
        emoji = request.data.get("emoji")

        if not all([message_uuid, user_id, emoji]):
            return Response({"error": "message_uuid, user_id, emoji are required"}, status=400)

        try:
            message = Message.objects.get(uuid=message_uuid)
            user = User.objects.get(id=user_id)
        except (Message.DoesNotExist, User.DoesNotExist):
            return Response({"error": "Message or user not found"}, status=404)

        reaction, created = MessageReaction.objects.get_or_create(
            message=message, user=user, reaction=emoji
        )
        if not created:
            # Toggle: already reacted → remove
            reaction.delete()
            return Response({"action": "removed", "username": user.username}, status=200)

        return Response({"action": "added", "username": user.username}, status=201)

class UserSuggestionsView(APIView):
    """
    Algoritmo de Sugerencias de Usuarios (Recomendación)
    Prioridades:
    1. Cierre Triádico: Personas que sigue el dueño del perfil pero tú no.
    2. Amigos en común: Personas con más conexiones mutuas contigo.
    3. Intereses: Personas con categorías de contenido similares.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        viewer = request.user
        target_user = get_object_or_404(User, username=username)

        # Cache key based on viewer and target
        cache_key = f"user_suggestions_{viewer.id}_{target_user.id}"
        cached_suggestions = cache.get(cache_key)
        if cached_suggestions:
            return Response(cached_suggestions, status=status.HTTP_200_OK)

        # Data sets for logic
        # viewer_following: IDs of people 'viewer' follows
        viewer_following = set(Follower.objects.filter(user_id=viewer).values_list('follower_user_id', flat=True))
        
        # 1. Triadic Closure (Priority 1: +20 pts)
        # People target_user follows but viewer doesn't
        target_following = Follower.objects.filter(user_id=target_user).values_list('follower_user_id', flat=True)
        
        scores = Counter()
        for uid in target_following:
            if uid != viewer.id and uid not in viewer_following:
                scores[uid] += 20

        # 2. Common Friends / Mutuals (Priority 2: +5 pts per mutual)
        # People who follow someone 'viewer' also follows
        # This is a bit heavy, limiting depth
        mutuals = Follower.objects.filter(
            user_id__in=viewer_following
        ).values_list('follower_user_id', flat=True)
        
        for uid in mutuals:
            if uid != viewer.id and uid not in viewer_following:
                scores[uid] += 5

        # 3. Shared Interests (+10 pts)
        # Match categories from viewer's liked videos
        viewer_liked_categories = Video.objects.filter(
            like_video_reverce__user_id=viewer
        ).values_list('category_id', flat=True).distinct()
        
        if viewer_liked_categories:
            users_in_categories = Video.objects.filter(
                category_id__in=viewer_liked_categories
            ).values_list('user_id', flat=True).distinct()
            
            for uid in users_in_categories:
                if uid != viewer.id and uid not in viewer_following:
                    scores[uid] += 10

        # Get top 20 suggested user IDs
        top_uids = [uid for uid, score in scores.most_common(20)]
        
        suggested_users = User.objects.filter(id__in=top_uids)
        
        # Format results using FollowerListSerializer (reusing for structure)
        # We wrap in a list of {"user": user_data, "is_following": False}
        results = []
        for user in suggested_users:
            results.append({
                "user": UserSerializers(user, context={'request': request}).data,
                "is_following": False, # By definition of our filtering
                "score": scores[user.id]
            })

        # Sort results by score just in case QuerySet order changed
        results.sort(key=lambda x: x['score'], reverse=True)

        # Cache for 10 minutes
        cache.set(cache_key, results, 600)

        return Response(results, status=status.HTTP_200_OK)


class VideoUploadAPIView(APIView):
    """
    Endpoint para subir videos de forma asíncrona.
    Soporta formato multipart/form-data.
    Guarda el video en estado 'pending' y lanza la tarea de IA.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        video_file = request.FILES.get('video')
        description = request.data.get('description', '')

        # Audio mixing params (optional)
        audio_track_url = request.data.get('audio_url') or None
        try:
            volume_original = float(request.data.get('volume_original', 1.0))
            volume_music    = float(request.data.get('volume_music',    0.8))
        except (TypeError, ValueError):
            volume_original, volume_music = 1.0, 0.8
        audio_track_id    = request.data.get('audio_id') or None
        audio_track_title = request.data.get('audio_title') or None
        audio_track_artist= request.data.get('audio_artist') or None
        audio_track_cover = request.data.get('audio_cover') or None
        try:
            audio_trim_start = float(request.data.get('audio_trim_start', 0.0))
        except (TypeError, ValueError):
            audio_trim_start = 0.0
        try:
            _ate = request.data.get('audio_trim_end')
            audio_trim_end = float(_ate) if _ate is not None else None
        except (TypeError, ValueError):
            audio_trim_end = None

        _privacy_raw = request.data.get('privacy', Video.PRIVACY_PUBLIC)
        privacy = _privacy_raw if _privacy_raw in (
            Video.PRIVACY_PUBLIC, Video.PRIVACY_FOLLOWERS, Video.PRIVACY_PRIVATE
        ) else Video.PRIVACY_PUBLIC

        if not video_file:
            return Response({"error": "No files provided"}, status=status.HTTP_400_BAD_REQUEST)

        # ── Duration limits: Normal = 60s, Premium = 300s ────────────────────
        try:
            video_duration = float(request.data.get('duration', 0))
        except (TypeError, ValueError):
            video_duration = 0

        if video_duration > 0:
            is_premium = False
            try:
                is_premium = request.user.buzzy_premium.is_active
            except Exception:
                pass

            max_seconds = 300 if is_premium else 60
            if video_duration > max_seconds:
                limit_label = '5 minutos' if is_premium else '1 minuto'
                return Response(
                    {"error": f"Tu plan permite videos de máximo {limit_label}. "
                              f"{'Actualiza a Premium para subir videos más largos.' if not is_premium else ''}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )


        video = Video.objects.create(
            user_id=request.user,
            video=video_file,
            description=description,
            status='pending',
            is_safe=False,
            tags=[],
            audio_track_url=audio_track_url,
            volume_original=volume_original,
            volume_music=volume_music,
            audio_track_id=audio_track_id,
            audio_track_title=audio_track_title,
            audio_track_artist=audio_track_artist,
            audio_track_cover=audio_track_cover,
            audio_trim_start=audio_trim_start,
            audio_trim_end=audio_trim_end,
            privacy=privacy,
        )
        
        # Parse and save hashtags from description
        if description:
            import re
            from apps.videos.models import Hashtag, VideoHashtag
            tags_found = re.findall(r'#(\w+)', description)
            for tag_name in set(tags_found):
                tag_name_lower = tag_name.lower()
                hashtag, created = Hashtag.objects.get_or_create(
                    name=tag_name_lower,
                    defaults={'videos_count': 0}
                )
                Hashtag.objects.filter(id=hashtag.id).update(videos_count=F('videos_count') + 1)
                VideoHashtag.objects.get_or_create(video_id=video, hashtag_id=hashtag)

        # Notificaciones de mención en la descripción del video
        _notify_mentions(description, actor=request.user, video=video)

        # Lanzar la tarea de moderación con IA en Celery
        try:
            process_video_ai.delay(video.id)
        except Exception as e:
            # Fallback en caso de que Celery no esté corriendo
            print(f"Error lanzando Celery: {e}")
            video.status = 'blocked'
            video.safety_label = 'Error interno Celery'
            video.save()
            return Response({"error": "Error interno del servidor de procesamiento."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        return Response({
            "message": "Video uploaded, AI processing started",
            "video_id": video.id,
            "status": video.status
        }, status=status.HTTP_201_CREATED)

    def get(self, request):
        video_id = request.query_params.get('id')
        if not video_id:
            return Response({"error": "ID not provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            video = Video.objects.get(id=video_id)
            return Response({
                "id": video.id,
                "status": video.status,
                "is_safe": video.is_safe,
                "safety_label": video.safety_label
            })
        except Video.DoesNotExist:
            return Response({"error": "Video not found"}, status=status.HTTP_404_NOT_FOUND)


# ─── Notification helpers ────────────────────────────────────────────────────

def _notify_mentions(text: str, actor, video=None, comment=None, story=None):
    """
    Parse @username mentions in text and send a MENTION notification to each
    mentioned user (skipping self-mentions and duplicates).
    """
    if not text:
        return
    import re
    from django.contrib.auth import get_user_model
    User = get_user_model()
    usernames = set(re.findall(r'@(\w+)', text))
    for username in usernames:
        try:
            mentioned_user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            continue
        if mentioned_user == actor:
            continue
        source = "historia" if story else ("comentario" if comment else "video")
        create_and_broadcast_notification(
            recipient=mentioned_user,
            actor=actor,
            notification_type=Notification.Type.MENTION,
            video=video,
            comment=comment,
            message=f"@{actor.username} te mencionó en un {source}",
        )


def _build_notification_message(notification_type: str, actor_username: str) -> str:
    messages = {
        Notification.Type.FOLLOW:        f"@{actor_username} empezó a seguirte",
        Notification.Type.LIKE:          f"@{actor_username} le dio me gusta a tu video",
        Notification.Type.COMMENT:       f"@{actor_username} comentó en tu video",
        Notification.Type.COMMENT_REPLY: f"@{actor_username} respondió tu comentario",
        Notification.Type.PROFILE_VISIT: f"@{actor_username} visitó tu perfil",
        Notification.Type.STORY_LIKE:    f"@{actor_username} le dio me gusta a tu historia",
        Notification.Type.GIFT:          f"@{actor_username} te envió un regalo",
        Notification.Type.MENTION:       f"@{actor_username} te mencionó",
    }
    return messages.get(notification_type, f"@{actor_username} interactuó contigo")


def create_and_broadcast_notification(
    recipient,
    actor,
    notification_type: str,
    video=None,
    comment=None,
    message: str = "",
) -> None:
    """
    Persist a Notification and push it via WebSocket in a fire-and-forget manner.
    Skips self-notifications silently.
    """
    if recipient == actor:
        return
    if not message:
        message = _build_notification_message(notification_type, actor.username)

    notif = Notification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=notification_type,
        video=video,
        comment=comment,
        message=message,
    )

    payload = {
        "event": "notification",
        "id": notif.id,
        "notification_type": notification_type,
        "message": message,
        "actor": {
            "id": actor.id,
            "username": actor.username,
            "profile_picture": _abs(actor.profile_picture.url if actor.profile_picture else None),
        },
        "video_uuid": str(video.uuid) if video else None,
        "video_thumbnail": video.thumbnail_url if video and video.thumbnail_url else None,
        "created_at": notif.created_at.isoformat(),
        "is_read": False,
    }

    try:
        requests.post(
            f"{settings.FASTAPI_WS_URL}/broadcast-notification/",
            json={"recipient_id": recipient.id, **payload},
            headers=_ws_headers(),
            timeout=2,
        )
    except Exception as e:
        print(f"[notification] WS broadcast failed: {e}")

    try:
        send_push_notification(
            user=recipient,
            title="Buzzy",
            body=message,
            data={
                "type": notification_type,
                "actor_username": actor.username,
                "video_uuid": str(video.uuid) if video else "",
            },
        )
    except Exception as e:
        print(f"[push] notification failed: {e}")


# ─── Notification API Views ──────────────────────────────────────────────────

class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = (
            Notification.objects
            .filter(recipient=request.user)
            .select_related('actor', 'video', 'comment')
            .order_by('-created_at')[:50]
        )
        serializer = NotificationSerializer(notifications, many=True, context={'request': request})
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"results": serializer.data, "unread_count": unread_count})


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Mark specific notifications as read, or all if no ids provided."""
        from django.utils import timezone as tz
        ids = request.data.get("ids")  # list of ints or None → mark all
        qs = Notification.objects.filter(recipient=request.user, is_read=False)
        if ids:
            qs = qs.filter(id__in=ids)
        qs.update(is_read=True, read_at=tz.now())
        return Response({"marked": qs.count() if not ids else len(ids)})


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"unread_count": count})


class AudioTrackListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AudioTrack.objects.filter(is_active=True)
        category = request.query_params.get('category')
        search = request.query_params.get('search')
        if category and category != 'all':
            qs = qs.filter(category=category)
        if search:
            qs = qs.filter(title__icontains=search) | qs.filter(artist__icontains=search)
        serializer = AudioTrackSerializer(qs, many=True, context={'request': request})
        return Response(serializer.data)


class FavoriteTrackView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        favs = FavoriteTrack.objects.filter(user=request.user).select_related('track')
        serializer = FavoriteTrackSerializer(favs, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        track_id = request.data.get('track_id')
        if not track_id:
            return Response({'error': 'track_id required'}, status=400)
        track = AudioTrack.objects.filter(id=track_id, is_active=True).first()
        if not track:
            return Response({'error': 'Track not found'}, status=404)
        fav, created = FavoriteTrack.objects.get_or_create(user=request.user, track=track)
        if not created:
            fav.delete()
            return Response({'favorited': False})
        serializer = FavoriteTrackSerializer(fav, context={'request': request})
        return Response({'favorited': True, 'favorite': serializer.data}, status=201)


class HashtagSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.videos.models import Hashtag
        q = request.query_params.get('q', '').strip().lstrip('#')
        qs = Hashtag.objects.all()
        if q:
            qs = qs.filter(name__icontains=q)
        qs = qs.order_by('-videos_count')[:20]
        data = [{'name': h.name, 'videos_count': h.videos_count} for h in qs]
        return Response(data)


class SavedVideoView(APIView):
    """
    GET  /api/videos/saved/        → lista videos guardados del usuario
    POST /api/videos/saved/        → guarda un video  { "video_id": <id> }
    DELETE /api/videos/saved/      → elimina un guardado { "video_id": <id> }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import SavedVideo
        saved = (
            SavedVideo.objects
            .filter(user=request.user)
            .select_related('video')
            .order_by('-saved_at')
        )
        videos = [s.video for s in saved]
        serializer = VideoZerializer(videos, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        from .models import SavedVideo
        video_id = request.data.get('video_id')
        if not video_id:
            return Response({'error': 'video_id requerido'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            video = Video.objects.get(id=video_id)
        except Video.DoesNotExist:
            return Response({'error': 'Video no encontrado'}, status=status.HTTP_404_NOT_FOUND)
        if video.status == 'blocked':
            return Response({'error': 'Video no disponible'}, status=status.HTTP_400_BAD_REQUEST)
        _, created = SavedVideo.objects.get_or_create(user=request.user, video=video)
        return Response({'saved': True, 'created': created})

    def delete(self, request):
        from .models import SavedVideo
        video_id = request.data.get('video_id')
        if not video_id:
            return Response({'error': 'video_id requerido'}, status=status.HTTP_400_BAD_REQUEST)
        SavedVideo.objects.filter(user=request.user, video_id=video_id).delete()
        return Response({'saved': False})
