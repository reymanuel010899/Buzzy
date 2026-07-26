from rest_framework import serializers
from .models import SubscriptionPlan, UserSubscription, SubscriptionBenefit, CallSession

class SubscriptionBenefitSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionBenefit
        fields = ['benefit_type', 'limit', 'description', 'order']

class SubscriptionPlanSerializer(serializers.ModelSerializer):
    benefits = SubscriptionBenefitSerializer(many=True, read_only=True)
    
    class Meta:
        model = SubscriptionPlan
        fields = ['id', 'name', 'description', 'price', 'is_active', 'benefits']

class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_info = serializers.SerializerMethodField()
    
    class Meta:
        model = UserSubscription
        fields = ['id', 'subscriber', 'subscribed_to', 'plan', 'plan_info', 'plan_name', 'start_date', 'end_date', 'is_active', 'comments_this_month', 'calls_this_month', 'video_calls_this_month', 'voice_seconds_this_month', 'video_seconds_consumed_this_month']

    def get_plan_info(self, obj):
        if obj.plan:
            benefits = SubscriptionBenefitSerializer(obj.plan.benefits.all(), many=True).data
            return {
                'id': obj.plan.id,
                'name': obj.plan.name,
                'price': obj.plan.price,
                'benefits': benefits
            }
        return None

    # For frontend compatibility with Navar.tsx which uses subscription_status.plan.name
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.plan:
            data['plan'] = {
                'id': instance.plan.id,
                'name': instance.plan.name
            }
        return data

class SubscriberListSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    plan_name = serializers.CharField(source='plan.name', read_only=True)

    class Meta:
        model = UserSubscription
        fields = ("user", "plan_name", "start_date", "is_active")

    def get_user(self, obj):
        from apps.videos.serializers import UserSerializers
        return UserSerializers(obj.subscriber, context=self.context).data


class CallSessionSerializer(serializers.ModelSerializer):
    caller_username = serializers.CharField(source='caller.username', read_only=True)
    callee_username = serializers.CharField(source='callee.username', read_only=True)

    class Meta:
        model = CallSession
        fields = [
            'uuid',
            'call_type',
            'channel_name',
            'allowed_seconds',
            'consumed_seconds',
            'status',
            'ended_reason',
            'started_at',
            'answered_at',
            'ended_at',
            'caller_username',
            'callee_username',
            'agora_uid_caller',
            'agora_uid_callee',
        ]
