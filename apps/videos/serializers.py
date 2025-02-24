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
        fields = "__all__"  
