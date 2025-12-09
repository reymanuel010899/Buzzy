import requests
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
# from apps.wallet.models import WalletModel
from .models import Comment, Follower, GiftStory, Like, Story, StoryGift, StoryLike, StoryMedia, StoryView, Video, View
from .serializers import CommentSerializers, FollowerSerializer, GetGiftStorySerializer, GiftRecivedSerializer, GiftStorySerializer, LikeSerializers, StoryLikeSerializer, StorySerializer, StoryViewSerializer, UserSerializers, VideoZerializer, ViewSerializers, formated_created
# Create your views here.

class ListMediaApiView(ListAPIView):
    serializer_class = VideoZerializer
    def get_queryset(self):
        return Video.objects.all()
    
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
                # "liked": liked
            }
            try:
                requests.post("http://localhost:8001/create-view/", json=ws_data)
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

            ws_data = {
                "event": "new_comment",
                "video_id": comment.video_id.id,  # <-- CORRECTO
                "content": comment.content,
                "user_id": UserSerializers(request.user).data,
                "created_at": str(comment.created_at),
                "uuid": str(comment.uuid),
                "parent_uuid": str(comment.parent.uuid) if comment.parent else None,
                "comments_count": comment.video_id.get_count_comment()  # <-- CORRECTO
            }

            try:
                requests.post("http://localhost:8001/create-comment/", json=ws_data)
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

        # Data para el WebSocket
        ws_data = {
            "event": "like_updated",
            "video_id": video.id,
            "likes": like_count,
            "liked": liked
        }

        # Notificar en FastAPI
        try:
            requests.post("http://localhost:8001/broadcast-like/", json=ws_data)
        except Exception as e:
            print("Error enviando evento WS:", e)

        # Respuesta HTTP
        message = "Like creado correctamente" if liked else "Like eliminado correctamente"

        return Response(
            {"message": message, "data": ws_data},
            status=status.HTTP_201_CREATED if liked else status.HTTP_200_OK
        )


class GetCommentsApiView(APIView):
    serializer_class = CommentSerializers

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
                    requests.post("http://localhost:8001/broadcast-follower/", json=ws_data)
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
                requests.post("http://localhost:8001/broadcast-follower/", json=ws_data)
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
            requests.post("http://localhost:8001/broadcast-story/", json=ws_data)
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
            requests.post("http://localhost:8001/broadcast-story/", json=ws_data)
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
         .order_by('-created_at')  # más recientes primero

        # 3. (Opcional pero PRO) → Ordenar para que tu story siempre aparezca PRIMERO
        story_list = list(stories)

        # Separar tu story (si existe)
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
            requests.post("http://localhost:8001/broadcast-story/", json=ws_data)
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
            requests.post("http://localhost:8001/broadcast-story/", json=ws_data)
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
            requests.post("http://localhost:8001/broadcast-story/", json=ws_data, timeout=2)
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
                }
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
            "from_user": request.user.id,
            "color_premiun": gift.gift.color_premiun if gift.gift.color_premiun else "blue"
            # "total_gifts": story_media.story.received_gifts.count()
        }

        try:
            requests.post("http://localhost:8001/broadcast-gift-story/", json=ws_data)
            
        except Exception as e:
            print("errpr",e )

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