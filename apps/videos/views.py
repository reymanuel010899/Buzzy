import random
from re import L
from django.shortcuts import get_object_or_404
import requests
from django.conf import settings
from apps.subscriptions.models import UserSubscription
from apps.recommendations.services import record_video_view, update_user_interests
from django.utils import timezone
from datetime import timedelta
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Exists, OuterRef
# from apps.wallet.models import WalletModel
from .models import ChatRoom, Comment, Follower, GiftStory, Like, Message, MessageReaction, Story, StoryGift, StoryLike, StoryMedia, StoryView, UserOnlineStatus, Video, VideoGift, VideoStats, View, User
from .serializers import ChatRoomSerializer,FollowerListSerializer, CommentSerializers, FollowerSerializer, GetGiftStorySerializer, GiftRecivedSerializer, GiftStorySerializer, LikeSerializers, ListCommentsZerializers, MessageSerializer, StoryLikeSerializer, StorySerializer, StoryViewSerializer, UserSerializers, VideoZerializer, ViewSerializers, formated_created
from apps.wallet.models import WalletModel
from apps.wallet.serializers import WalletSerializer
from django.core.cache import cache
from collections import Counter
from django.db.models import F, ExpressionWrapper, FloatField, Case, When, Value
from django.db.models.functions import Extract


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
class ListMediaApiView(ListAPIView):
    serializer_class = VideoZerializer
    def get_queryset(self):
        return Video.objects.filter(status='ready').order_by("-created_at")
    
class CreateViewApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ViewSerializers
    def post(self, request, *args, **kwargs):
        video_id = request.data.get("video_id")
        try:
            video = Video.objects.get(id=video_id)
            # Aquí puedes implementar la lógica para registrar la vista
            like, created = View.objects.get_or_create(user_id=request.user, video_id=video)
            if not created:
                return Response(
                    {"message": "La vista ya ha sido registrada anteriormente"},
                    status=status.HTTP_200_OK
                )
            
            ws_data = {
                "event": "new_view",
                "video_id": video.id,
                "view_acount": video.get_count_view(),
                "user_id": request.user.id,
                "video_user_id": video.user_id.id,
                # "liked": liked
            }
            try:
                requests.post(f"{settings.FASTAPI_WS_URL}/create-view/", json=ws_data)
            except Exception as e:
                print("Error enviando evento WS:", e)

            record_video_view(request.user.id, video.id)
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
    Accepted event_types: video_start | video_engagement | video_view_valid

    For video_view_valid: creates a View record (triggering the WS notification)
    and increments VideoStats.valid_views atomically. A 60-minute cooldown
    prevents the same user from inflating the counter via rapid replays.
    """
    permission_classes = [IsAuthenticated]

    VALID_EVENTS = {'video_start', 'video_engagement', 'video_view_valid'}
    COUNTER_MAP = {
        'video_start': 'starts',
        'video_engagement': 'engagements',
        'video_view_valid': 'valid_views',
    }

    def post(self, request, *args, **kwargs):
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

        # --- Deduplication for valid views (60-minute cooldown) ---
        if event_type == 'video_view_valid':
            cutoff = timezone.now() - timedelta(hours=1)
            already_viewed = View.objects.filter(
                user_id=request.user,
                video_id=video,
                created_at__gte=cutoff
            ).exists()

            if already_viewed:
                return Response(
                    {'message': 'Vista válida ya registrada en la última hora.'},
                    status=status.HTTP_200_OK
                )

            # Create the View record (triggers WS notification via existing logic)
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
                    requests.post(f"{settings.FASTAPI_WS_URL}/create-view/", json=ws_data, timeout=2)
                except Exception as e:
                    print('Error enviando evento WS (VideoEventView):', e)

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

        validate_data = self.serializer_class(data=request.data)

        if validate_data.is_valid():
            # Obtener parent si viene
            parent_uuid = request.data.get("parent_uuid", None)
            parent = None

            if parent_uuid:
                try:
                    parent = Comment.objects.filter(uuid=parent_uuid).first()
                except Comment.DoesNotExist:
                    parent = None

            # Crear el comentario
            comment = validate_data.save(
                user_id=request.user,
                is_priority_comment=priority_comment_enabled,
                priority_plan_name=priority_plan_name
            )
            if comment and parent:
                comment.parent = parent
                comment.save()

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
                requests.post(f"{settings.FASTAPI_WS_URL}/create-comment/", json=ws_data)
            except Exception as e:
                print("Error enviando evento WS:", e)

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
            requests.post(f"http://localhost:8001/broadcast-like/", json=ws_data)
        except Exception as e:
            print("Error enviando evento WS:", e)

        # Respuesta HTTP
        message = "Like creado correctamente" if liked else "Like eliminado correctamente"
        
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
                    requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-follower/", json=ws_data)
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
                requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-follower/", json=ws_data)
            except Exception as e:
                print("Error enviando evento WS:", e)

            chat_room = ChatRoom.objects.filter(participant1=serialized_data.validated_data['follower_user_id'], participant2=request.user)
            return Response(
                {"message": "Seguiendo correctamente", "data": serialized_data.data, "chat_uuid": chat_room[0].uuid if len(chat_room) > 0 else  "" },
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
   
        # Primero creamos la historia
        story = Story.objects.create(
            user=request.user,
            text=text
        )

        # Creamos los archivos multimedia
        for i, file in enumerate(files):
            media_type = "image" if "image" in file.content_type else "video"
            StoryMedia.objects.create(
                story=story,
                file=file,
                type=media_type,
                order=i
            )

        serializer = self.serializer_class(story)

        ws_data = {
            "event": "new_story",
            "user_id": request.user.id,
            "story_uuid": story.uuid,
            "story": serializer.data,
            "total_media": story.media.count(),
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data)
        except:
            pass

        return Response(
            {"message": "Historia creada correctamente", "data": serializer.data},
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
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data)
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
        stories = Story.objects.filter(user_id=user_id, is_active=True).order_by("-created_at")

        for story in stories:
            story.mark_expired()

        stories = stories.filter(is_active=True)

        serializer = self.serializer_class(stories, many=True)
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
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data)
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
            "profile_picture": v.user.profile_picture.url if v.user.profile_picture else '',
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
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data)
        except:
            pass

        return Response({"message": "Historia eliminada"}, status=200)


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

        # 2. Obtener el tipo de 
        if gift_type == "🦁":
            gift_type = "leon"
        elif gift_type ==  "❤️":
            gift_type = "te-amo"
        elif gift_type ==  "💕":
            gift_type = "te-amo"
        elif gift_type ==  "🔥":
            gift_type = "fuego"
        elif gift_type ==  "🪙":
            gift_type = "bitcoin"
        elif gift_type == "🪐":
            gift_type =  "Space"
 
        try:
            gift_obj = GiftStory.objects.get(slug=gift_type, is_active=True)
        except GiftStory.DoesNotExist:
            return Response({"error": "Este regalo no existe"}, status=404)

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

        # Descontar tokens
        wallet.tokens -= int(gift_obj.token_price)
        wallet.save()

        obj, created = StoryView.objects.get_or_create(story=story_media.story, user=request.user)
        gift = StoryGift.objects.create(
            user=story_media.story.user,   # dueño de la historia
            sender=request.user,           # el que regala
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
            "gift_video": gift_obj.video.url if gift_obj.video else None,
            "from_user": request.user.id,
            "total_gifts": story_media.story.received_gifts.count(),
            "color_premiun": gift.gift.color_premiun if gift.gift.color_premiun else "blue"
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, timeout=2)
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

        # 2. Normalizar emoji a slug
        emoji_to_slug = {
            "🦁": "leon",
            "❤️": "te-amo",
            "💕": "te-amo",
            "🔥": "fuego",
            "🪙": "bitcoin",
            "🪐": "Space"
        }
        gift_typ = emoji_to_slug.get(gift_type, gift_type)

        try:
            gift_obj = GiftStory.objects.get(slug=gift_typ, is_active=True)
        except GiftStory.DoesNotExist:
            return Response({"error": "Este regalo no existe"}, status=404)

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
            gift_type=gift_type
        )

        # 4. WebSocket notification
        ws_data = {
            "event": "video_gift_received",
            "video_id": video.id,
            "gift_uuid": gift.uuid,
            "gift_type": gift_type,
            "amount": gift_obj.token_price,
            "sender": gift.sender.username,
            "gift_video": gift_obj.video.url if gift_obj.video else None,
            "from_user": request.user.id,
            "to_user": video.user_id.id,
            "total_gifts": video.received_gifts.count(),
            "color_premiun": gift_obj.color_premiun if gift_obj.color_premiun else "blue"
        }

        try:
            import requests as http_requests
            http_requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-story/", json=ws_data, timeout=2)
        except Exception:
            pass

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
            "gift_video": gift.gift.video.url if gift.gift.video.url else None,
            "amount": gift.gift.token_price,
            "sender": gift.sender.username,
            "to_user": gift.story.user.id,
            "color_premiun": gift.gift.color_premiun if gift.gift.color_premiun else "blue"
            # "total_gifts": story_media.story.received_gifts.count()
        }

        try:
            requests.post(f"{settings.FASTAPI_WS_URL}/broadcast-gift-story/", json=ws_data)

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
    
class ChatListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Subconsulta: ¿existe al menos un mensaje en este chat?
        has_messages = Message.objects.filter(chat_room=OuterRef('pk'))

        chats = ChatRoom.objects.filter(
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

        serializer = ChatRoomSerializer(chats, many=True, context={'request': request})
        return Response({
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

        # Crear mensaje
        message = Message.objects.create(
            chat_room=chat,
            sender=request.user,
            content=content,
            message_type=message_type,
            file=request.FILES.get("file")  # Si envías imagen/video/voz
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

        # Enviar al FastAPI para broadcast en tiempo real
        try:
            requests.post(f"{FASTAPI_WS_URL}/broadcast-chat/", json=ws_payload, timeout=3)
        except Exception as e:
            print("Error enviando mensaje al WebSocket:", e)
            # No fallar la API si el WS falla

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

from rest_framework.parsers import MultiPartParser, FormParser
from .tasks import process_video_ai

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
        
        if not video_file:
            return Response({"error": "No files provided"}, status=status.HTTP_400_BAD_REQUEST)
            
        video = Video.objects.create(
            user_id=request.user,
            video=video_file,
            description=description,
            status='pending',
            is_safe=False,
            tags=[]
        )
        
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

