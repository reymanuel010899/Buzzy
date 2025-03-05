from django.utils import timezone
import datetime
from datetime import timedelta
from rest_framework import serializers
from .models import Comment, Follower,AIGenerationHistory, GiftStory, Like, Story, StoryGift, StoryLike, StoryMedia, StoryView, Video, View, ChatRoom, Message, UserOnlineStatus, MessageReaction
from apps.users.models import User


class UserSerializers(serializers.ModelSerializer):
     profile_picture = serializers.ImageField(use_url=False)
     subscription_status = serializers.SerializerMethodField()

     class Meta:
        model = User
        fields = ("username", "email", 'profile_picture', 'id', 'subscription_status') 

     def get_subscription_status(self, obj):
        from apps.subscriptions.models import UserSubscription
        from apps.subscriptions.serializers import UserSubscriptionSerializer
        
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

    class Meta:
        model = Comment
        fields = [ 'uuid','video_id', 'content', 'user_id', 'created_at', 'parent', 'is_priority_comment', 'priority_plan_name']
        extra_kwargs = {
            "user_id": {"required": False},
            "parent": {"required": False},
        }

    def get_user_id(self, obj):
        # We pass the video owner as context to the user serializer
        # so it can check the 1-to-1 subscription for premium status in comments
        context = self.context.copy()
        context['subscribed_to_user'] = obj.video_id.user_id
        return UserSerializers(obj.user_id, context=context).data

    # def create(self, validated_data):
    #     # Sacamos el parent_uuid que viene del request
    #     parent_uuid = validated_data.pop("parent_uuid", None)

    #     parent = None
    #     if parent_uuid:
    #         parent = Comment.objects.filter(uuid=parent_uuid).first()

    #     # No duplicamos `parent`
    #     return Comment.objects.create(
    #         parent=parent,
    #         **validated_data
    #     )

    user_id = serializers.SerializerMethodField()
    parent_uuid = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    class Meta:
        model = Comment
        fields = ("video_id", "content", "user_id", "uuid", "created_at", "parent_uuid", "is_priority_comment", "priority_plan_name")
        extra_kwargs = {
            "user": {"required": False},
            "parent": {"required": False},
        }

    def create(self, validated_data):
        # Sacamos parent del validated_data por si vino del request
        parent = validated_data.pop("parent", None)

        # Creamos el comentario correctamente
        return Comment.objects.create(parent=parent, **validated_data)
    
    # def get_event(self, obj):
    #     return ""
    


    class Meta:
        model = Comment
        fields = ['uuid', 'video_id', 'content', 'user_id', 'created_at', 'parent_uuid', 'is_priority_comment', 'priority_plan_name']

    def create(self, validated_data):
        parent_uuid = validated_data.pop("parent_uuid", None)

        parent = None
        if parent_uuid:
            try:
                parent = Comment.objects.get(uuid=parent_uuid)
            except Comment.DoesNotExist:
                parent = None

        return Comment.objects.create(parent=parent, **validated_data)
class ListCommentsZerializers(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    parent = CommentSerializers(read_only=True)
    class Meta:
        model = Comment
        fields = [ 'uuid','video_id', 'content', 'user_id', 'created_at', 'parent', 'is_priority_comment', 'priority_plan_name']
    
    def get_user_id(self, obj):
        context = self.context.copy()
        context['subscribed_to_user'] = obj.video_id.user_id
        return UserSerializers(obj.user_id, context=context).data
        
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
    class Meta:
        model = Video
        fields = ("id","category", "created_at","tags",  "description", "duration","thumbnail_url", "user_id", "video_url", "video", "like_count", "comments_count", "view_acount", "liked", "current_user_followered", "uuid", "media_type") 

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
    file = serializers.ImageField(use_url=False)
    class Meta:
        model = StoryMedia
        fields = ['id', 'file', 'type', 'order']

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
    class Meta:
        model = StoryGift
        fields = "__all__"

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
    sender_avatar = serializers.CharField(source='sender.profile_picture', read_only=True)
    sender_subscription_status = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()

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
        fields = ['uuid', 'content', 'sender_username', 'sender_avatar', 'created_at', 'message_type', 'file', 'reactions', 'sender_subscription_status']

class ChatRoomSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_user_online = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatRoom
        fields = ['uuid', 'other_user', 'last_message', 'unread_count', 'updated_at', 'other_user_online']
    
    def get_other_user(self, obj):
        user = self.context['request'].user
        other = obj.get_other_participant(user)
        return {
            'id': other.id,
            'username': other.username,
            'name': other.first_name + ' ' + other.last_name,
            'avatar': other.profile_picture.url if other.profile_picture else None,
            'profile_video': other.profile_video.url if other.profile_video else None,
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
        return last_msg.content[:50] + '...' if last_msg else None
    
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
