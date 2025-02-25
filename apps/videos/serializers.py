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
        print(obj.get_count_view(), "********")
        return obj.get_count_view()
