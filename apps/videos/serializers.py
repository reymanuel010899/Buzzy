from django.utils import timezone
import datetime
from datetime import timedelta
from rest_framework import serializers
from .models import Comment, Follower, GiftStory, Like, Story, StoryGift, StoryLike, StoryMedia, StoryView, Video, View
from apps.users.models import User


class UserSerializers(serializers.ModelSerializer):
     profile_picture = serializers.ImageField(use_url=False)
     class Meta:
        model = User
        fields = ("username", "email", 'profile_picture', 'id') 

class LikeSerializers(serializers.ModelSerializer):
    class Meta:
        model = Like
        fields = ("video_id",)
class CommentSerializers(serializers.ModelSerializer):
    user_id = UserSerializers(read_only=True)
    parent_uuid = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Comment
        fields = ['uuid', 'video_id', 'content', 'user_id', 'created_at', 'parent']
        extra_kwargs = {
            "user_id": {"required": False},
            "parent": {"required": False},
        }

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

    user_id = UserSerializers(read_only=True)
    parent_uuid = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    class Meta:
        model = Comment
        fields = ("video_id", "content", "user_id", "uuid", "created_at", "parent_uuid")
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
        fields = ['uuid', 'video_id', 'content', 'user_id', 'created_at', 'parent_uuid']

    def create(self, validated_data):
        parent_uuid = validated_data.pop("parent_uuid", None)

        parent = None
        if parent_uuid:
            try:
                parent = Comment.objects.get(uuid=parent_uuid)
            except Comment.DoesNotExist:
                parent = None

        return Comment.objects.create(parent=parent, **validated_data)

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
        fields = ("id","category", "created_at","tags",  "description", "duration","thumbnail_url", "user_id", "video_url", "video", "like_count", "comments_count", "view_acount", "liked", "current_user_followered", "uuid") 

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




formated_created = StorySerializer()