from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .models import Video
from .serializers import VideoZerializer
# Create your views here.

class ListMediaApiView(ListAPIView):
    serializer_class = VideoZerializer
    def get_queryset(self):
        return Video.objects.all()
    