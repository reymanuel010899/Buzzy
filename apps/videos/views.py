
from rest_framework.generics import ListAPIView
from django.conf import settings
from .serializers import VideoZerializer, VideoSerializerMeta
from rest_framework.permissions import IsAuthenticated
from .utils import extract_geolocation_from_video
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.core.files.storage import default_storage
from .models import Video
from .utils import extract_geolocation_from_video
import os
import uuid

class VideoUploadView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return Response({'error': 'Usuario no autenticado'}, status=status.HTTP_401_UNAUTHORIZED)

        request_data = request.data.copy()
        if 'user_id' not in request_data:
            request_data['user_id'] = user.id

        serializer = VideoSerializerMeta(data=request_data)
        print(request_data, "*********************")
        if serializer.is_valid():
            video_file = request.POST.get('video')
            if not video_file:
                return Response({'error': 'No se proporcionó un video'}, status=status.HTTP_400_BAD_REQUEST)

            # Generar un nombre único para el archivo
            file_extension = os.path.splitext(video_file)[1]
            file_name = f"{uuid.uuid4()}{file_extension}"
            print(file_name, "-------------")
            file_path = default_storage.save(os.path.join('contenido', file_name), video_file)

            # Obtener la ruta completa del archivo
            full_path = os.path.join(settings.MEDIA_ROOT, file_path)

            # Extraer metadatos de geolocalización
            metadata = extract_geolocation_from_video(full_path)

            # Crear el objeto Video con los datos proporcionados y los metadatos
            video_data = serializer.validated_data
            video_data['video'] = file_path
            video_data['latitude'] = metadata['latitude']
            video_data['longitude'] = metadata['longitude']

            video = serializer.save()

            return Response(VideoSerializerMeta(video).data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class ListMediaApiView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = VideoZerializer
    def get_queryset(self):
        return Video.objects.all()
