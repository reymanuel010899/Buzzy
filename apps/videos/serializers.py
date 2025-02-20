from rest_framework import serializers
from .models import Video
from apps.users.models import User
class UserSerializers(serializers.ModelSerializer):
     class Meta:
        model = User
        fields = ("username", "email", 'profile_picture') 

class VideoZerializer(serializers.ModelSerializer):
    user_id = UserSerializers()
    class Meta:
        model = Video
        fields = [
            "id",
            "user_id",
            "category",
            "video_url",
            "video",
            "thumbnail_url",
            "description",
            "tags",
            "created_at",
            "updated_at",
            "duration",
            "likes_count",
            "comments_count",
        ]