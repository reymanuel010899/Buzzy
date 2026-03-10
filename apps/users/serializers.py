from rest_framework import serializers
from . import models

class DetailedUserSerializer(serializers.ModelSerializer):
    like_all_count = serializers.SerializerMethodField(read_only=True)
    comments_all_count = serializers.SerializerMethodField(read_only=True)
    view_all_acount = serializers.SerializerMethodField(read_only=True)
    follower_all_acount = serializers.SerializerMethodField(read_only=True)
    total_social_followers = serializers.SerializerMethodField(read_only=True)
    followed_all_acount = serializers.SerializerMethodField(read_only=True)
    is_following = serializers.SerializerMethodField(read_only=True)
    subscription_status = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = models.User
        fields = ('id','first_name', 'email', 'profile_picture', 'profile_video', 'like_all_count', 'comments_all_count', 'view_all_acount', 'follower_all_acount', 'total_social_followers', 'followed_all_acount', 'is_following', 'subscription_status')

    def get_subscription_status(self, obj):
        try:
            from apps.subscriptions.serializers import UserSubscriptionSerializer
            return UserSubscriptionSerializer(obj.subscription).data
        except:
            return None

    def get_is_following(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            from apps.videos.models import Follower
            return Follower.objects.filter(user_id=request.user, follower_user_id=obj).exists()
        return False

    def get_like_all_count(self, obj):
        return obj.all_likes()
    
    def get_comments_all_count(self, obj):
        return obj.all_comments()
    
    def get_view_all_acount(self, obj):
        return obj.all_views()
    
    def get_follower_all_acount(self, obj):
        # Seguidores internos de Buzzy
        return obj.all_followers().count()
    
    def get_total_social_followers(self, obj):
        # Seguidores externos unidos de Instagram + Facebook + TikTok
        return obj.total_social_followers()
    
    def get_followed_all_acount(self, obj):
        return obj.all_followed().count()
    
class LoginZerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    access_token = serializers.CharField()

class TrendingSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Trending
        fields = ('id', 'term', 'count', 'updated_at')

class RecentSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.RecentSearch
        fields = ('id', 'term', 'created_at')


class SocialAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.SocialAccount
        fields = ('platform', 'platform_username', 'platform_user_id', 'followers_count', 'connected_at')
        read_only_fields = fields