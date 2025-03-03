from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status
from apps.videos.serializers import  VideoZerializer
from apps.videos.models import Video
from .models import User
from .serializers import LoginZerializer, DetailedUserSerializer
class LoginView(APIView):
    # authentication_class = (TokenAuthentication,)
    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        user = User.objects.filter(email=email).first()
        if self.request.user and user.check_password(password):
            refresh = RefreshToken.for_user(user)
            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                       "profile_picture": user.profile_picture.url if user.profile_picture else 'media/profile_pics/avatar.webp',
                }
            }, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Credenciales inválidas"}, status=status.HTTP_401_UNAUTHORIZED)
   
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]  # Solo usuarios autenticados pueden hacer logout

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")  # Obtener el refresh token del request
            token = RefreshToken(refresh_token)
            token.blacklist()  # Invalidar el token agregándolo a la lista negra

            return Response({"message": "Logout exitoso"}, status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response({"error": "Token inválido o expirado"}, status=status.HTTP_400_BAD_REQUEST)
        

class RegisterView(APIView):
    def post(self, request):
        name = request.data.get('name')
        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')
        confirm_password = request.data.get('repeat_password')
        # Validar que las contraseñas coincidan
        if password != confirm_password:
            return Response({
            "error": "Las contraseñas no coinciden."
        }, status=status.HTTP_404_NOT_FOUND)

        # Validar que el nombre de usuario no esté ya en uso
        if User.objects.filter(username=username).exists():
            return Response({
            "error": "El username ya está en uso"
        }, status=status.HTTP_404_NOT_FOUND)

        # Validar que el correo electrónico no esté ya en uso
        if User.objects.filter(email=email).exists():
            return Response({
            "error": "El correo electrónico ya está en uso"
        }, status=status.HTTP_404_NOT_FOUND)

        # Crear el usuario
        user = User.objects.create_user(email=email, username=username, password=password,  first_name=name)

        # Generar tokens
        refresh = RefreshToken.for_user(user)

        # Retornar los tokens y los datos del usuario
        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "profile_picture": user.profile_picture.url if user.profile_picture else 'http://localhost:8000/media/profile_pics/avatar.webp',
            },
        }, status=status.HTTP_201_CREATED)
    
class DetaildUser(APIView):
    serializer_class = DetailedUserSerializer
    permission_classes = [IsAuthenticated]
    def get(self, request, username, *args, **kwargs):
        user = User.objects.get(username=username)
        serialised_user = self.serializer_class(user)
        return Response({
            "user":  serialised_user.data,
        }, status=status.HTTP_200_OK)
    
class MediaByUser(APIView):
    serializer_class =  VideoZerializer
    # authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        user = User.objects.get(username=username)
        media = Video.objects.filter(user_id=user)
        serialised_user = self.serializer_class(media, many=True)
        return Response({
            "media_user":  serialised_user.data,
        }, status=status.HTTP_200_OK)


