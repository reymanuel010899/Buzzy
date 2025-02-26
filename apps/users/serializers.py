from rest_framework import serializers
from . import models

class DetailedUserSerializer(serializers.ModelSerializer):
    like_all_count = serializers.SerializerMethodField(read_only=True)
    comments_all_count = serializers.SerializerMethodField(read_only=True)
    view_all_acount = serializers.SerializerMethodField(read_only=True)
    follower_all_acount = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.User
        fields = ('id','first_name', 'email', 'profile_picture', 'like_all_count', 'comments_all_count', 'view_all_acount', 'follower_all_acount')

    def get_like_all_count(self, obj):
        return obj.all_likes()
    
    def get_comments_all_count(self, obj):
        return obj.all_comments()
    
    def get_view_all_acount(self, obj):
        return obj.all_views()
    
    def get_follower_all_acount(self, obj):
        return obj.all_followers()
    
class LoginZerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    access_token = serializers.CharField()
    