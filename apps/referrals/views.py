from django.conf import settings
from django.shortcuts import render
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .models import ReferralToken, ReferralProfile
from .serializers import ReferralTokenSerializer, ReferralProfileSerializer


class GenerateReferralTokenView(APIView):
    """
    POST /api/referrals/generate/
    Genera un token de referido de un solo uso con TTL de 30 días.
    Límite: 10 tokens activos simultáneos por usuario para evitar spam/análisis masivo.
    Si ya tiene 10 activos, reutiliza el más reciente.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone

        # Limpiar tokens expirados del usuario antes de contar
        ReferralToken.objects.filter(
            owner=request.user,
            expires_at__lt=timezone.now()
        ).update(is_active=False)

        # Si ya tiene un token activo vigente, reutilizarlo en lugar de crear otro
        existing = (
            ReferralToken.objects
            .filter(owner=request.user, is_active=True, expires_at__gt=timezone.now())
            .order_by('-created_at')
            .first()
        )
        if existing:
            serializer = ReferralTokenSerializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)

        token = ReferralToken.objects.create(owner=request.user)
        serializer = ReferralTokenSerializer(token)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ReferralStatsView(APIView):
    """
    GET /api/referrals/stats/
    Retorna el progreso de referidos del usuario autenticado.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = ReferralProfile.objects.get_or_create(user=request.user)
        serializer = ReferralProfileSerializer(profile)
        return Response(serializer.data)


def join_redirect_view(request):
    """
    GET /join?code=TOKEN
    Página intermedia que intenta abrir la app nativa (buzzy://join?code=TOKEN).
    Si la app no está instalada después de 2.5s, redirige a Play Store.
    Si no viene code, redirige directamente al signup web.
    """
    code = request.GET.get('code', '')
    frontend_url = settings.FRONTEND_URL.rstrip('/')
    play_store_url = settings.PLAY_STORE_URL

    signup_url = f"{frontend_url}/sign-up?code={code}" if code else f"{frontend_url}/sign-up"

    return render(request, 'referrals/join.html', {
        'code': code,
        'signup_url': signup_url,
        'play_store_url': play_store_url,
    })
