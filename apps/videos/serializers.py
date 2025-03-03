from rest_framework import serializers
from .models import Video
from apps.users.models import User
class UserSerializers(serializers.ModelSerializer):
     class Meta:
        model = User
        fields = ("username", "email", 'profile_picture') 

class VideoZerializer(serializers.ModelSerializer):
    user_id = UserSerializers()
    like_count = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    view_acount = serializers.SerializerMethodField()
    class Meta:
        model = Video
        fields = ("id","category", "created_at",  "description", "duration","thumbnail_url", "user_id", "video_url", "video", "like_count", "comments_count", "view_acount") 

    def get_like_count(self, obj):
        return obj.get_count_like()
    
    def get_comments_count(self, obj):
        return obj.get_count_comment()
    
    def get_view_acount(self, obj):
        return obj.get_count_view()


class VideoSerializerMeta(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())  # ✅ Corrección aquí()
    class Meta:
        model = Video
        fields = ("id","category", "created_at",  "description","thumbnail_url", "user_id", "video_url", "video") 


class videoSerializerDetail(serializers.Serializer):
    video = serializers.CharField()
    video_url = serializers.CharField()
    thumbnail_url = serializers.CharField()
    video_id = serializers.CharField()
    created_at = serializers.CharField()

    #  class Meta:
    #     model = Video
    #     fields = ("id","category", "created_at",  "description",
    #                "duration","thumbnail_url", "user_id", "video_url", "video", "like_count", "comments_count", "view_acount") 