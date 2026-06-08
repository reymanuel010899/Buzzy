from django.db import models
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import BuzzyBanner, BannerView, BannerInteraction
from .serializers import BuzzyBannerSerializer


def _get_pending_banners(user):
    """
    Retorna todos los banners activos y no descartados para el usuario,
    ordenados por prioridad: PERSONAL > GRUPO > GLOBAL, luego por fecha.
    """
    now = timezone.now()
    user_group_ids = user.group_memberships.values_list('group_id', flat=True)
    dismissed_ids = BannerView.objects.filter(
        user=user, dismissed=True
    ).values_list('banner_id', flat=True)

    base_qs = BuzzyBanner.objects.filter(
        is_active=True
    ).exclude(
        id__in=dismissed_ids
    ).filter(
        models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
    )

    personal = list(base_qs.filter(target='PERSONAL', user=user).order_by('-created_at'))
    group    = list(base_qs.filter(target='GROUP', group_id__in=user_group_ids).order_by('-created_at'))
    global_  = list(base_qs.filter(target='GLOBAL').order_by('-created_at'))

    # Deduplicar manteniendo orden de prioridad
    seen = set()
    result = []
    for b in personal + group + global_:
        if b.id not in seen:
            seen.add(b.id)
            result.append(b)
    return result


class ActiveBannerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Devuelve la cola completa de banners pendientes para el usuario."""
        user = request.user
        banners = _get_pending_banners(user)

        if not banners:
            return Response({"banners": [], "count": 0})

        # Registrar vista de todos los que se van a mostrar
        for banner in banners:
            BannerView.objects.get_or_create(user=user, banner=banner)

        return Response({
            "banners": BuzzyBannerSerializer(banners, many=True).data,
            "count": len(banners),
        })

    def post(self, request):
        """
        Acciones sobre un banner:
        - action=dismiss  → descarta el banner
        - action=click    → registra click (para analytics)
        """
        banner_id = request.data.get('banner_id')
        action = request.data.get('action', 'dismiss')

        if not banner_id:
            return Response({"error": "banner_id requerido"}, status=400)

        try:
            banner = BuzzyBanner.objects.get(id=banner_id)
        except BuzzyBanner.DoesNotExist:
            return Response({"error": "Banner no encontrado"}, status=404)

        if action == 'dismiss':
            view, _ = BannerView.objects.get_or_create(user=request.user, banner=banner)
            view.dismissed = True
            view.save()

        BannerInteraction.objects.create(
            user=request.user,
            banner=banner,
            action=action,
        )

        return Response({"ok": True})
