from rest_framework import serializers
from .models import ReferralToken, ReferralProfile


class ReferralTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralToken
        fields = ('token', 'expires_at', 'created_at')
        read_only_fields = fields


class ReferralProfileSerializer(serializers.ModelSerializer):
    next_milestone = serializers.SerializerMethodField()
    progress_to_next = serializers.SerializerMethodField()

    class Meta:
        model = ReferralProfile
        fields = ('total_invitados', 'next_milestone', 'progress_to_next')

    def get_next_milestone(self, obj):
        remainder = obj.total_invitados % 5
        return obj.total_invitados + (5 - remainder) if remainder != 0 else obj.total_invitados + 5

    def get_progress_to_next(self, obj):
        return obj.total_invitados % 5
