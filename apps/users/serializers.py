from rest_framework import serializers
from . import models
class DetailedUserSerializer(serializers.Serializer):
    class Meta:
        model = models.User
        fields = "__all__"

class LoginZerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    access_token = serializers.CharField()
    