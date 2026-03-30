import random
from datetime import timedelta
from django.utils import timezone
from django.db.models import Case, When, FloatField, Value

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.videos.models import Video
from apps.videos.serializers import VideoZerializer
from .utils import get_redis_client

class HybridFeedAPIView(APIView):
    """
    (B) Capa Online/Hot: Motor de Feed Híbrido.
    Resuelve el Retrieval Híbrido inyectando pesos directamente en SQL
    y combinándolo con un decay de frescura en RAM.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        redis_client = get_redis_client()
        print(redis_client, "*********")
        # 1. Obtener de Redis la lista de IDs que el usuario ya vio (O(1))
        seen_key = f"seen:{user.id}"
        seen_videos = redis_client.smembers(seen_key)
        seen_list = list(seen_videos) if seen_videos else []
        print(seen_list, "vistos")
        # 2. Obtener el diccionario de intereses del usuario (O(1))
        interests_key = f"profile:{user.id}"
        interests = redis_client.hgetall(interests_key)
        
        # 3. Preparar QuerySet: Videos de últimos 30 días, seguros, excluyendo vistos
        thirty_days_ago = timezone.now() - timedelta(days=30)
        queryset = Video.objects.filter(
            created_at__gte=thirty_days_ago,
            status='ready',
            is_safe=True
        ).exclude(id__in=seen_list) # Filtrado nativo SQL de IDs excluidos
        
        # MANEJO DE COLD START (Si no hay intereses o el usuario es muy nuevo)
        if not interests:
            print("----- el usuario es nuevo le mandare los 20 -------")
            # Traer los más recientes disponibles
            videos = list(queryset.order_by('-created_at')[:20])
            
            # Fallback Extremo: Si el queryset está vacío (vio todo lo de los últimos 30 días)
            if not videos:
                videos = list(Video.objects.filter(status='ready', is_safe=True).exclude(id__in=seen_list).order_by('-created_at')[:20])
                
            serializer = VideoZerializer(videos, many=True, context={'request': request})
            return Response(serializer.data)
            
        # 4. Scoring SQL Dinámico: Inyectar pesos (Interest Score)
        whens = []
        for cat_id_str, score_str in interests.items():
            if cat_id_str.isdigit():
                whens.append(
                    When(category_id=int(cat_id_str), then=Value(float(score_str)))
                )
        queryset = queryset.annotate(
            interest_score=Case(
                *whens,
                default=Value(0.0),
                output_field=FloatField()
            )
        )
        
        # Traer los top 200 candidatos más relevantes a memoria (esto es rapidísimo)
        top_candidates = list(queryset.order_by('-interest_score', '-created_at')[:200])
      
        if not top_candidates:
            fallback = list(Video.objects.filter(status='ready', is_safe=True).exclude(id__in=seen_list).order_by('-created_at')[:20])
            serializer = VideoZerializer(fallback, many=True, context={'request': request})
            return Response(serializer.data)
            
        # 5. Ranking Híbrido en memoria
        now = timezone.now()
        scored_candidates = []
        
        for video in top_candidates:
            interest = getattr(video, 'interest_score', 0.0)
            
            # Calculo de frescura: 1.0 = ahora mismo, 0.0 = hace 30 días
            age = (now - video.created_at).total_seconds()
            max_age = 30 * 24 * 60 * 60  # 30 días en segundos
            freshness = max(0.0, 1.0 - (age / max_age))
            
            # Fórmula Híbrida: 70% Interés + 30% Frescura
            final_score = (interest * 0.7) + (freshness * 0.3)
            scored_candidates.append((final_score, video))

        print( scored_candidates, "********** los intereses *")    
        # Ordenar de mayor a menor final_score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        
        # 6. Muestreo y Mezcla (Exploración 20% / Explotación 80%)
        if len(scored_candidates) > 20:
            # 80% Explotación (Los 16 mejores hits obligatorios)
            exploitation = [x[1] for x in scored_candidates[:16]]
            
            # 20% Exploración (4 seleccionados al azar del siguiente pool para evitar burbujas)
            exploration_pool = [x[1] for x in scored_candidates[16:100]] 
            exploration_count = min(4, len(exploration_pool))
            exploration = random.sample(exploration_pool, exploration_count)
            
            final_videos = exploitation + exploration
            random.shuffle(final_videos) # Barajar el feed final
        else:
            final_videos = [x[1] for x in scored_candidates[:20]]
            
        # 7. Respuesta idéntica a la anterior para 0 fricción con el Frontend
        serializer = VideoZerializer(final_videos, many=True, context={'request': request})
        return Response(serializer.data)
