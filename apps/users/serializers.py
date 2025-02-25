from rest_framework import serializers
from . import models
class DetailedUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.User
        # fields = "__all__"
        exclude = ['password', 'groups', 'user_permissions', 'is_active', 'is_staff']

class LoginZerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    access_token = serializers.CharField()
    