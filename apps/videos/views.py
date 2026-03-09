from re import L
from django.shortcuts import get_object_or_404
import requests
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Exists, OuterRef
# from apps.wallet.models import WalletModel
from .models import ChatRoom, Comment, Follower, GiftStory, Like, Message, MessageReaction, Story, StoryGift, StoryLike, StoryMedia, StoryView, UserOnlineStatus, Video, View, User
from .serializers import ChatRoomSerializer, CommentSerializers, FollowerSerializer, GetGiftStorySerializer, GiftRecivedSerializer, GiftStorySerializer, LikeSerializers, ListCommentsZerializers, MessageSerializer, StoryLikeSerializer, StorySerializer, StoryViewSerializer, UserSerializers, VideoZerializer, ViewSerializers, formated_created
from apps.wallet.models import WalletModel
from apps.wallet.serializers import WalletSerializer


# Create your views here.
FASTAPI_WS_URL = "http://localhost:8001"
class ListMediaApiView(ListAPIView):
    serializer_class = VideoZerializer
    def get_queryset(self):
        return Video.objects.all().order_by("-created_at")
    
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

            return Response(
                {"message": "Vista registrada correctamente"},
                status=status.HTTP_201_CREATED
            )
        except Video.DoesNotExist:
            return Response(
                {"error": "Video no encontrado"},
                status=status.HTTP_404_NOT_FOUND
            )


class CreateCommentApiView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializers

    def post(self, request, *args, **kwargs):
        # Check subscription limits
        try:
            subscription = request.user.subscription
            can_comment, message = subscription.can_post_comment()
            if not can_comment:
                return Response({"error": message}, status=status.HTTP_403_FORBIDDEN)
        except Exception:
            # User doesn't have a subscription record yet (should be rare due to signals)
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
           
            comment = validate_data.save(user_id=request.user)
            if comment and parent:
                comment.parent = parent
                comment.save()

            # Increment comment count for VIPs
            try:
                subscription = request.user.subscription
                if subscription.plan and subscription.plan.name == 'VIP':
                    subscription.comments_this_month += 1
                    subscription.save()
            except Exception:
                pass

            ws_data = {
                "event": "new_comment",
                "video_id": comment.video_id.id,
                "video_user_id": comment.video_id.user_id.id,
                "content": comment.content,
                "user_id": UserSerializers(request.user).data,
                "created_at": str(comment.created_at),
                "uuid": str(comment.uuid),
                "parent": self.serializer_class(comment.parent).data,
                "comments_count": comment.video_id.get_count_comment()
            }

            try:
                requests.post(f"{settings.FASTAPI_WS_URL}/create-comment/", json=ws_data)
            except Exception as e:
                print("Error enviando evento WS:", e)

            return Response(
                {"message": "Comentario creado correctamente", "data": validate_data.data},
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
            return Response(
                {"message": "Seguiendo correctamente", "data": serialized_data.data},
                status=status.HTTP_201_CREATED
            )

        return Response(
            {"message": "Funcionalidad de seguir usuario no implementada aún."},
            status=status.HTTP_400_BAD_REQUEST
        )
    

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

        if not user_id:
            return Response({"error": "user_id requerido"}, status=400)

        try:
            user = User.objects.get(id=user_id)
            status, created = UserOnlineStatus.objects.get_or_create(
                user=user,
                defaults={'is_online': False}
            )
            status.is_online = is_online
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
