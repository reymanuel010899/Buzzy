from django.utils import timezone
import datetime
from datetime import timedelta
from django.conf import settings as django_settings
from rest_framework import serializers


def _abs_url(request, path):  # path: str | None
    """Convert a relative media path to an absolute URL using the request or BACKEND_URL."""
    if not path:
        return None
    if path.startswith("http"):
        return path
    if request:
        return request.build_absolute_uri(path)
    base = getattr(django_settings, "BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
from .models import AudioTrack, Comment, Follower, AIGenerationHistory, AIPackage, FavoriteTrack, GiftStory, Like, Story, StoryGift, StoryLike, StoryMedia, StoryView, Video, VideoGift, UserGift, View, ChatRoom, Message, UserOnlineStatus, MessageReaction, SavedVideo
from apps.users.models import User
from apps.subscriptions.models import UserSubscription
from apps.subscriptions.serializers import UserSubscriptionSerializer
        

class UserSerializers(serializers.ModelSerializer):
    profile_picture = serializers.SerializerMethodField(read_only=True)
    subscription_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("username", "email", 'profile_picture', 'id', 'subscription_status') 

    def get_profile_picture(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.profile_picture.url if obj.profile_picture else None)

    def get_subscription_status(self, obj):
 
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        # Check for specific 'subscribed_to_user' in context (e.g. video owner for comments)
        target_user = self.context.get('subscribed_to_user')
        
        if target_user:
            # 1-to-1: Is 'obj' (commenter) subscribed to 'target_user' (video owner)?
            subscription = UserSubscription.objects.filter(
                subscriber=obj,
                subscribed_to=target_user,
                is_active=True
            ).first()
            
            if subscription:
                return UserSubscriptionSerializer(subscription).data
            return None

        # Fallback to standard bidirectional check for other views
        # 1. Is 'obj' subscribed to viewer?
        subscription = UserSubscription.objects.filter(
            subscriber=obj,
            subscribed_to=request.user,
            is_active=True
        ).first()

        # 2. Is viewer subscribed to 'obj'?
        if not subscription:
            subscription = UserSubscription.objects.filter(
                subscriber=request.user,
                subscribed_to=obj,
                is_active=True
            ).first()

        if subscription:
            return UserSubscriptionSerializer(subscription).data
        return None

class LikeSerializers(serializers.ModelSerializer):
    
    class Meta:
        model = Like
        fields = ("video_id",)

   
class CommentSerializers(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    parent_uuid = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    audio_file = serializers.FileField(required=False, allow_null=True)
    audio_url = serializers.SerializerMethodField()
    image_file = serializers.ImageField(required=False, allow_null=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = (
            "uuid", "video_id", "content", "user_id", "created_at",
            "parent_uuid", "is_priority_comment", "priority_plan_name",
            "audio_file", "audio_url", "audio_duration",
            "image_file", "image_url",
        )
        extra_kwargs = {
            "user_id": {"required": False},
            "parent": {"required": False},
            "content": {"required": False},
        }

    def get_user_id(self, obj):
        context = self.context.copy()
        context['subscribed_to_user'] = obj.video_id.user_id
        return UserSerializers(obj.user_id, context=context).data

    def get_audio_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.audio_file.url if obj.audio_file else None)

    def get_image_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.image_file.url if obj.image_file else None)

    def create(self, validated_data):
        parent_uuid = validated_data.pop("parent_uuid", None)
        parent = None
        if parent_uuid:
            try:
                parent = Comment.objects.get(uuid=parent_uuid)
            except Comment.DoesNotExist:
                pass
        return Comment.objects.create(parent=parent, **validated_data)
class ListCommentsZerializers(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    parent = CommentSerializers(read_only=True)
    audio_url = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['uuid', 'video_id', 'content', 'user_id', 'created_at', 'parent',
                  'is_priority_comment', 'priority_plan_name', 'audio_url', 'audio_duration',
                  'image_url']

    def get_user_id(self, obj):
        context = self.context.copy()
        context['subscribed_to_user'] = obj.video_id.user_id
        return UserSerializers(obj.user_id, context=context).data

    def get_audio_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.audio_file.url if obj.audio_file else None)

    def get_image_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.image_file.url if obj.image_file else None)

class ViewSerializers(serializers.ModelSerializer):
    class Meta:
        model = View
        fields = ("user_id", "video_id", "uuid")

class VideoZerializer(serializers.ModelSerializer):
    user_id = UserSerializers()
    like_count = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    view_acount = serializers.SerializerMethodField()
    liked = serializers.SerializerMethodField()
    current_user_followered = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    audio_track_url = serializers.SerializerMethodField()
    audio_track_cover = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = (
            "id", "category", "created_at", "tags", "description", "duration",
            "thumbnail_url", "user_id", "video_url", "video", "like_count",
            "comments_count", "view_acount", "liked", "current_user_followered",
            "uuid", "media_type", "status",
            "audio_track_url", "audio_track_id", "audio_track_title",
            "audio_track_artist", "audio_track_cover", "volume_original",
            "volume_music", "audio_trim_start", "audio_trim_end",
            "privacy", "is_saved",
        )

    def get_video_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.video_url or (obj.video.url if obj.video else None))

    def get_thumbnail_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.thumbnail_url)

    def get_audio_track_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.audio_track_url)

    def get_audio_track_cover(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.audio_track_cover)

    def get_like_count(self, obj):
        return obj.get_count_like()

    def get_comments_count(self, obj):
        return obj.get_count_comment()

    def get_view_acount(self, obj):
        return obj.get_count_view()

    def get_liked(self, obj):
        user = self.context.get('request').user
        if user.is_authenticated:
            return Like.objects.filter(video_id=obj, user_id=user).exists()
        return False
    
    def get_current_user_followered(self, obj):
        user = self.context.get('request').user
        if user.is_authenticated:
            return Follower.objects.filter(follower_user_id=obj.user_id, user_id=user).exists()
        return False

    def get_is_saved(self, obj):
        user = self.context.get('request').user
        if user.is_authenticated:
            return SavedVideo.objects.filter(video=obj, user=user).exists()
        return False
    
class FollowerSerializer(serializers.ModelSerializer):
    # follower_user_id = UserSerializers()
    class Meta:
        model = Follower
        fields = ("follower_user_id",)

class FollowerListSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()

    class Meta:
        model = Follower
        fields = ("user", "is_following", "created_at")

    def get_user(self, obj):
        # Depending on whether we want followers or following, we return the opposite side
        request_user = self.context.get('view_target_user') # The user whose profile we are viewing
        if obj.user_id == request_user:
            # We are looking at people this user FOLLOWS
            return UserSerializers(obj.follower_user_id, context=self.context).data
        else:
            # We are looking at people who FOLLOW this user
            return UserSerializers(obj.user_id, context=self.context).data

    def get_is_following(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        
        # Who is the user in this row?
        request_user = self.context.get('view_target_user')
        target_user = obj.follower_user_id if obj.user_id == request_user else obj.user_id
        
        return Follower.objects.filter(user_id=request.user, follower_user_id=target_user).exists()

class StoryMediaSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()

    class Meta:
        model = StoryMedia
        fields = ['id', 'file', 'type', 'order', 'story']

    def get_file(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.file.url if obj.file else None)

class GiftStorySerializer(serializers.ModelSerializer):
    # user_liked = serializers.SerializerMethodField()

    class Meta:
        model = GiftStory
        fields = ("name", "slug", "emoji", "video", "token_price", "is_active", "created_at")

    # def get_user_liked(self, obj):
    #     user = self.context.get('request').user
    #     return  StoryLike.objects.filter(user=user, story=obj.sent_gifts__user).exists()
        

class GetGiftStorySerializer(serializers.ModelSerializer):
    class Meta:
        model = StoryGift
        fields = ("id", "user", "story", "gift", "gift_type", "sender", "quantity", "created_at","is_active")

class GiftRecivedSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    gift_video_url = serializers.SerializerMethodField()
    gift_type = serializers.CharField(source='gift.emoji', read_only=True)
    video_thumbnail = serializers.SerializerMethodField()

    def get_gift_video_url(self, obj):
        request = self.context.get('request')
        if obj.gift and obj.gift.video:
            return _abs_url(request, obj.gift.video.url)
        return None

    def get_video_thumbnail(self, obj):
        request = self.context.get('request')
        if obj.gift and obj.gift.thumbnail:
            return _abs_url(request, obj.gift.thumbnail.url)
        return None

    class Meta:
        model = StoryGift
        fields = "__all__"

class VideoGiftReceivedSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    sender_avatar = serializers.CharField(source='sender.profile_picture', read_only=True)
    gift_name = serializers.CharField(source='gift.name', read_only=True)
    gift_emoji = serializers.CharField(source='gift.emoji', read_only=True)
    gift_video_url = serializers.SerializerMethodField()
    gift_color = serializers.CharField(source='gift.color_premiun', read_only=True)
    video_thumbnail = serializers.SerializerMethodField()

    def get_gift_video_url(self, obj):
        request = self.context.get('request')
        if obj.gift.video:
            return _abs_url(request, obj.gift.video.url)
        return None

    def get_video_thumbnail(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.video.thumbnail_url if obj.video else None)

    class Meta:
        model = VideoGift
        fields = ['uuid', 'sender_username', 'sender_avatar', 'gift_name', 'gift_emoji',
                  'gift_video_url', 'gift_color', 'video_thumbnail', 'created_at', 'is_seen', 'quantity', 'vip_message']


class UserGiftReceivedSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    sender_avatar = serializers.CharField(source='sender.profile_picture', read_only=True)
    gift_name = serializers.CharField(source='gift.name', read_only=True)
    gift_emoji = serializers.CharField(source='gift.emoji', read_only=True)
    gift_color = serializers.CharField(source='gift.color_premiun', read_only=True)
    gift_video_url = serializers.SerializerMethodField()
    video_thumbnail = serializers.SerializerMethodField()

    def get_gift_video_url(self, obj):
        request = self.context.get('request')
        if obj.gift.video:
            return _abs_url(request, obj.gift.video.url)
        return None

    def get_video_thumbnail(self, obj):
        request = self.context.get('request')
        if obj.gift.thumbnail:
            return _abs_url(request, obj.gift.thumbnail.url)
        return None

    class Meta:
        model = UserGift
        fields = ['uuid', 'sender_username', 'sender_avatar', 'gift_name', 'gift_emoji',
                  'gift_video_url', 'gift_color', 'video_thumbnail', 'created_at', 'is_seen', 'quantity', 'vip_message']


class StorySerializer(serializers.ModelSerializer):
    media = StoryMediaSerializer(many=True, read_only=True)
    total_views = serializers.SerializerMethodField()
    user = UserSerializers()
    formatted_created_at = serializers.SerializerMethodField()

    def get_total_views(self, obj):
        return obj.total_views()

    def get_formatted_created_at(self, obj):
        now = timezone.now()
        if isinstance(obj, datetime.datetime):
            diff = now - obj
        else:
            diff = now - obj.created_at
        if diff > timedelta(days=1):
            days = diff.days
            return f"{days} {'día' if days == 1 else 'días'}"
        elif diff > timedelta(hours=1):
            hours = diff.seconds // 3600
            return f"{hours} {'hora' if hours == 1 else 'horas'}"
        else:
            minutes = diff.seconds // 60
            return f"{minutes} {'minuto' if minutes == 1 else 'minutos'}"

    class Meta:
        model = Story
        fields = "__all__"
        read_only_fields = ("uuid", "created_at", "is_active", "user", "formatted_created_at")


class StoryViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoryView
        fields = "__all__"
        read_only_fields = ("viewed_at",)

class StoryLikeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoryLike
        fields = "__all__"
        read_only_fields = ("liked_at",)





class MessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    sender_id = serializers.IntegerField(source='sender.id', read_only=True)
    sender_avatar = serializers.CharField(source='sender.profile_picture', read_only=True)
    sender_subscription_status = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()
    forwarded_from_username = serializers.CharField(source='forwarded_from.username', read_only=True, allow_null=True)

    def get_sender_subscription_status(self, obj):
        from apps.subscriptions.models import UserSubscription
        from apps.subscriptions.serializers import UserSubscriptionSerializer
        
        # We need to know who the other participant is to check the 1-to-1 sub
        # Message has chat_room
        chat = obj.chat_room
        viewer = self.context.get('request').user
        if not viewer.is_authenticated:
            return None
            
        other = chat.get_other_participant(obj.sender)
        # Check if sender is subscribed to the OTHER participant in this chat
        subscription = UserSubscription.objects.filter(
            subscriber=obj.sender,
            subscribed_to=other,
            is_active=True
        ).first()
        
        if subscription:
            return UserSubscriptionSerializer(subscription).data
        return None

    def get_reactions(self, obj):
        """Return { emoji: [username, ...] } grouped dict"""
        result = {}
        for r in obj.reactions.select_related('user').all():
            result.setdefault(r.reaction, []).append(r.user.username)
        return result

    class Meta:
        model = Message
        fields = ['uuid', 'content', 'sender_username', 'sender_id', 'sender_avatar', 'created_at', 'message_type', 'file', 'reactions', 'sender_subscription_status', 'story_uuid', 'story_media_url', 'story_audio_url', 'deleted_for_all', 'is_read', 'forwarded_from_username', 'is_edited']

class ChatRoomSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_user_online = serializers.SerializerMethodField()
    folder_type = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['uuid', 'other_user', 'last_message', 'unread_count', 'updated_at', 'other_user_online', 'folder_type']

    def get_folder_type(self, obj):
        """Devuelve el folder personal del viewer, no el del otro participante."""
        request = self.context.get('request')
        if not request:
            return obj.folder_type_p1
        return obj.get_folder_for(request.user)
    
    def get_other_user(self, obj):
        user = self.context['request'].user
        other = obj.get_other_participant(user)
        return {
            'id': other.id,
            'username': other.username,
            'name': other.first_name + ' ' + other.last_name,
            'avatar': _abs_url(self.context.get('request'), other.profile_picture.url if other.profile_picture else None),
            'profile_video': _abs_url(self.context.get('request'), other.profile_video.url if other.profile_video else None),
            'subscription_status': self.get_subscription_status(other),
        }
    
    def get_subscription_status(self, other_user):
        from apps.subscriptions.models import UserSubscription
        from apps.subscriptions.serializers import UserSubscriptionSerializer
        
        viewer = self.context['request'].user
        if not viewer.is_authenticated:
            return None

        # 1. Is the other user subscribed to me? (So I see them as premium)
        sub_to_viewer = UserSubscription.objects.filter(
            subscriber=other_user,
            subscribed_to=viewer,
            is_active=True
        ).first()
        
        if sub_to_viewer:
            return UserSubscriptionSerializer(sub_to_viewer).data

        # 2. Am I (viewer) subscribed to the other user? (So I see myself as premium/having benefits)
        sub_from_viewer = UserSubscription.objects.filter(
            subscriber=viewer,
            subscribed_to=other_user,
            is_active=True
        ).first()
        
        if sub_from_viewer:
            return UserSubscriptionSerializer(sub_from_viewer).data

        return None
    
    def get_last_message(self, obj):
        last_msg = obj.messages.last()
        if not last_msg:
            return None
        msg_type = getattr(last_msg, 'message_type', 'text')
        if msg_type == 'contact':
            try:
                import json
                contact = json.loads(last_msg.content)
                return f"Contacto: @{contact.get('username', '')}"
            except Exception:
                return "Contacto compartido"
        if msg_type == 'voice':
            return "🎤 Audio"
        if msg_type in ('image',):
            return "📷 Imagen"
        if msg_type == 'video':
            return "🎥 Video"
        if msg_type in ('document', 'file'):
            return "📄 Documento"
        content = last_msg.content or ""
        return (content[:50] + '...') if len(content) > 50 else content
    
    def get_unread_count(self, obj):
        user = self.context['request'].user
        return obj.unread_count_p1 if user == obj.participant1 else obj.unread_count_p2
    
    def get_other_user_online(self, obj):
        user = self.context['request'].user
        other = obj.get_other_participant(user)
        
        status, created = UserOnlineStatus.objects.get_or_create(
            user=other,
            defaults={'is_online': False}
        )
        
        return {
            'is_online': status.is_online,
            'last_seen': status.last_seen.isoformat() if not status.is_online else None
        }
    
formated_created = StorySerializer()

from .models import AIStyle, AITemplate

class AITemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AITemplate
        fields = ['id', 'title', 'prompt', 'image_url', 'media_type', 'order']

class AIStyleSerializer(serializers.ModelSerializer):
    templates = AITemplateSerializer(many=True, read_only=True)

    class Meta:
        model = AIStyle
        fields = ['id', 'name', 'slug', 'description', 'icon_name', 'color_bg', 'color_text', 'color_border', 'order', 'templates']

class AIGenerationHistorySerializer(serializers.ModelSerializer):
    style_name = serializers.CharField(source='style.name', read_only=True)
    
    class Meta:
        model = AIGenerationHistory
        fields = ['id', 'prompt', 'media_url', 'media_type', 'style_name', 'created_at']


class AIPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIPackage
        fields = ['id', 'name', 'description', 'videos_count', 'images_count', 'price', 'is_featured', 'order']


class NotificationSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    video_thumbnail = serializers.SerializerMethodField()
    video_uuid = serializers.SerializerMethodField()

    class Meta:
        from .models import Notification
        model = Notification
        fields = [
            'id', 'notification_type', 'message', 'is_read', 'read_at',
            'created_at', 'actor', 'video_thumbnail', 'video_uuid',
        ]

    def get_actor(self, obj):
        if not obj.actor:
            return None
        return {
            'id': obj.actor.id,
            'username': obj.actor.username,
            'profile_picture': _abs_url(self.context.get('request'), obj.actor.profile_picture.url if obj.actor.profile_picture else None),
        }

    def get_video_thumbnail(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.video.thumbnail_url if obj.video else None)

    def get_video_uuid(self, obj):
        if obj.video:
            return str(obj.video.uuid)
        return None


class AudioTrackSerializer(serializers.ModelSerializer):
    cover_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()
    duration  = serializers.CharField(source='duration_display', read_only=True)

    class Meta:
        model  = AudioTrack
        fields = ('id', 'title', 'artist', 'cover_url', 'audio_url', 'duration', 'duration_secs', 'category')

    def get_cover_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.cover.url if obj.cover else None)

    def get_audio_url(self, obj):
        request = self.context.get('request')
        return _abs_url(request, obj.audio_file.url if obj.audio_file else None)


class FavoriteTrackSerializer(serializers.ModelSerializer):
    track = AudioTrackSerializer(read_only=True)

    class Meta:
        model  = FavoriteTrack
        fields = ('id', 'track', 'created_at')
