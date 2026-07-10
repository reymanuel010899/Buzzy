from rest_framework import serializers
from . import models
from apps.subscriptions.models import UserSubscription
from apps.subscriptions.serializers import UserSubscriptionSerializer

class DetailedUserSerializer(serializers.ModelSerializer):
    like_all_count = serializers.SerializerMethodField(read_only=True)
    comments_all_count = serializers.SerializerMethodField(read_only=True)
    view_all_acount = serializers.SerializerMethodField(read_only=True)
    follower_all_acount = serializers.SerializerMethodField(read_only=True)
    total_social_followers = serializers.SerializerMethodField(read_only=True)
    followed_all_acount = serializers.SerializerMethodField(read_only=True)
    is_following = serializers.SerializerMethodField(read_only=True)
    subscribers_count = serializers.SerializerMethodField(read_only=True)
    subscription_status = serializers.SerializerMethodField(read_only=True)
    am_i_subscribed = serializers.SerializerMethodField(read_only=True)
    has_active_stories = serializers.SerializerMethodField(read_only=True)
    profile_picture = serializers.SerializerMethodField(read_only=True)
    chat_security = serializers.SerializerMethodField(read_only=True)
    is_buzzy_premium = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.User
        fields = ('id','username', 'first_name', 'email', 'bio', 'profile_picture', 'profile_video', 'like_all_count', 'comments_all_count', 'view_all_acount', 'follower_all_acount', 'total_social_followers', 'followed_all_acount', 'is_following', 'subscribers_count', 'subscription_status', 'am_i_subscribed', 'has_active_stories', 'chat_security', 'is_buzzy_premium', 'is_owner', 'onboarding_completed')

    def get_profile_picture(self, obj):

        if obj.profile_picture:
            return obj.profile_picture.url
        return None

    def get_subscription_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        # Check bidirectional: 
        # 1. Is viewer subscribed to the profile OWNER (obj)?
        subscription = UserSubscription.objects.filter(
            subscriber=request.user,
            subscribed_to=obj,
            is_active=True
        ).first()

        # 2. Is profile OWNER (obj) subscribed to viewer?
        if not subscription:
            subscription = UserSubscription.objects.filter(
                subscriber=obj,
                subscribed_to=request.user,
                is_active=True
            ).first()

        if subscription:
            return UserSubscriptionSerializer(subscription).data
        return None

    def get_am_i_subscribed(self, obj):
        """¿El viewer está suscrito activamente a ESTE perfil? (dirección única).
        Se usa para mostrar la pestaña 'Suscriptores' solo si corresponde."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        if request.user.id == obj.id:
            return True  # el dueño siempre puede ver su propia sección
        return UserSubscription.objects.filter(
            subscriber=request.user, subscribed_to=obj, is_active=True
        ).exists()

    def get_is_following(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            from apps.videos.models import Follower
            return Follower.objects.filter(user_id=request.user, follower_user_id=obj).exists()
        return False

    def get_subscribers_count(self, obj):
        from apps.subscriptions.models import UserSubscription
        return UserSubscription.objects.filter(subscribed_to=obj, is_active=True).count()

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

    def get_has_active_stories(self, obj):
        from apps.videos.models import Story
        from django.utils import timezone
        from datetime import timedelta
        limit = timezone.now() - timedelta(hours=24)
        return Story.objects.filter(user=obj, is_active=True, created_at__gte=limit).exists()

    def get_chat_security(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or request.user != obj:
            return None

        from .models import UserSecurity
        security = UserSecurity.objects.filter(user=obj).first()
        if not security:
            return None

        return {
            "has_pin": bool(security.chat_pin_hash),
            "hidden_verified_at": security.hidden_pin_verified_at,
            "hidden_verified": bool(security.hidden_pin_verified_at),
        }

    def get_is_buzzy_premium(self, obj):
        try:
            return obj.buzzy_premium.is_active
        except Exception:
            return False

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
