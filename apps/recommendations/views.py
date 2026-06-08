import random
from django.utils import timezone
from django.db.models import F, ExpressionWrapper, FloatField, Case, When, Value, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.videos.models import Video, Follower
from apps.videos.serializers import VideoZerializer
from .utils import get_redis_client


def _privacy_filter(user) -> Q:
    """
    Construye el filtro Q de privacidad para un usuario autenticado.

    Reglas:
      - public    → siempre visible
      - followers → visible si el viewer sigue al autor Y el autor sigue al viewer
                    (follow mutuo = "amigos")
      - private   → solo el propio autor
    """
    if user is None or not user.is_authenticated:
        return Q(privacy=Video.PRIVACY_PUBLIC)

    # IDs de usuarios que me siguen
    followers_of_me = Follower.objects.filter(
        follower_user_id=user
    ).values_list('user_id_id', flat=True)

    # IDs de usuarios a quienes sigo
    i_follow = Follower.objects.filter(
        user_id=user
    ).values_list('follower_user_id_id', flat=True)

    # Follow mutuo: están en ambas listas
    mutual_ids = set(followers_of_me) & set(i_follow)

    return (
        Q(privacy=Video.PRIVACY_PUBLIC) |
        Q(privacy=Video.PRIVACY_FOLLOWERS, user_id__in=mutual_ids) |
        Q(privacy=Video.PRIVACY_PRIVATE, user_id=user)
    )

# ─── Constantes del algoritmo ────────────────────────────────────────────────

COLD_START_THRESHOLD = 5      # menos de N vistas = usuario nuevo
FEED_PAGE_SIZE       = 10     # videos por llamada
EXPLOIT_RATIO        = 0.80   # 80% de los mejores hits
CANDIDATE_POOL       = 200    # cuántos candidatos traer de BD antes de re-rankear
FRESHNESS_WINDOW     = 60     # días máximos de antigüedad para el score de frescura

# Cuánto vale cada señal de engagement en el score final de un video
VIDEO_SCORE_WEIGHTS = {
    'valid_views': 0.5,
    'engagements': 0.3,
    'likes':       0.2,
}

# Distribución del score final del feed: cuánto pesa cada componente
FEED_SCORE_WEIGHTS = {
    'interest':  0.60,   # preferencias del usuario por categoría
    'freshness': 0.25,   # qué tan reciente es el video
    'popularity': 0.15,  # viralidad global del video
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _cold_start_videos(seen_ids: list, limit: int = FEED_PAGE_SIZE, user=None) -> list:
    """
    Devuelve los mejores videos por popularidad real para usuarios nuevos.
    Garantiza diversidad de categorías distribuyendo slots equitativamente.
    """
    privacy_q = _privacy_filter(user)
    base_qs = (
        Video.objects
        .filter(privacy_q, status='ready', is_safe=True, category__isnull=False)
        .select_related('category', 'stats')
        .annotate(
            pop_score=ExpressionWrapper(
                (F('stats__valid_views') * VIDEO_SCORE_WEIGHTS['valid_views']) +
                (F('stats__engagements') * VIDEO_SCORE_WEIGHTS['engagements']),
                output_field=FloatField()
            )
        )
    )
    if seen_ids:
        base_qs = base_qs.exclude(id__in=seen_ids)

    # Trae los top 60 por score global y luego distribuye por categoría en RAM
    candidates = list(base_qs.order_by('-pop_score', '-created_at')[:60])

    # Fallback: si no hay videos nuevos, ignorar seen_ids y repetir contenido
    # (mejor mostrar videos conocidos que dejar el feed vacío)
    if not candidates:
        candidates = list(
            Video.objects
            .filter(privacy_q, status='ready', is_safe=True, category__isnull=False)
            .select_related('category', 'stats')
            .annotate(
                pop_score=ExpressionWrapper(
                    (F('stats__valid_views') * VIDEO_SCORE_WEIGHTS['valid_views']) +
                    (F('stats__engagements') * VIDEO_SCORE_WEIGHTS['engagements']),
                    output_field=FloatField()
                )
            )
            .order_by('-pop_score', '-created_at')[:60]
        )

    # Distribuye: máx 3 videos por categoría para no saturar el feed
    by_category: dict = {}
    result = []
    for v in candidates:
        cat = v.category_id
        if by_category.get(cat, 0) < 3:
            result.append(v)
            by_category[cat] = by_category.get(cat, 0) + 1
        if len(result) >= limit:
            break

    # Si no llegamos a `limit`, completamos con el resto sin restricción de categoría
    if len(result) < limit:
        already = {v.id for v in result}
        for v in candidates:
            if v.id not in already:
                result.append(v)
            if len(result) >= limit:
                break

    return result


def _hybrid_score(video, interests: dict, now, max_age_seconds: float) -> float:
    """
    Calcula el score final de un video para un usuario concreto.
    Fórmula: 60% interés por categoría + 25% frescura + 15% popularidad global.
    """
    # Interés del usuario por la categoría del video (normalizado a 0-1)
    raw_interest = float(interests.get(str(video.category_id), 0.0))
    # Normalizamos dividiendo por el interés máximo (evita overflow de score)
    max_interest = float(interests.get('__max__', 1.0)) or 1.0
    interest = min(raw_interest / max_interest, 1.0)

    # Frescura: 1.0 = publicado ahora, 0.0 = hace FRESHNESS_WINDOW días
    age_seconds = (now - video.created_at).total_seconds()
    freshness = max(0.0, 1.0 - (age_seconds / max_age_seconds))

    # Popularidad del video (normalizada, safe con getattr por si no tiene stats)
    valid_views = getattr(getattr(video, 'stats', None), 'valid_views', 0) or 0
    engagements = getattr(getattr(video, 'stats', None), 'engagements', 0) or 0
    # Escala logarítmica para que videos muy virales no aplasten a todo
    import math
    popularity = math.log1p(
        valid_views * VIDEO_SCORE_WEIGHTS['valid_views'] +
        engagements * VIDEO_SCORE_WEIGHTS['engagements']
    ) / 10.0  # /10 para mantenerlo en rango ~0-1

    return (
        interest   * FEED_SCORE_WEIGHTS['interest'] +
        freshness  * FEED_SCORE_WEIGHTS['freshness'] +
        popularity * FEED_SCORE_WEIGHTS['popularity']
    )


def _mark_delivered(redis_client, user_id: int, videos: list) -> None:
    """Marca los videos entregados al feed como vistos en Redis (pipeline atómico)."""
    if not videos:
        return
    key = f"seen:{user_id}"
    pipe = redis_client.pipeline()
    pipe.sadd(key, *[str(v.id) for v in videos])
    pipe.expire(key, 30 * 24 * 60 * 60)
    pipe.execute()


# ─── Endpoint principal ───────────────────────────────────────────────────────

class HybridFeedAPIView(APIView):
    """
    Feed híbrido inteligente.

    Flujo:
      1. Usuario nuevo (< COLD_START_THRESHOLD vistas): devuelve los 20 videos
         más populares con diversidad de categorías — mismo resultado que list-home
         pero sin duplicar lógica.
      2. Usuario con algo de historial pero sin perfil de intereses todavía:
         devuelve los más recientes que no haya visto.
      3. Usuario con perfil de intereses: ranking híbrido (interés + frescura +
         popularidad) con 80/20 explotación/exploración para enganchar sin crear
         burbujas de filtro.

    El perfil del usuario crece automáticamente con cada like/vista/comentario
    gracias a update_user_interests() en los otros endpoints.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        redis = get_redis_client()
        # ── 1. ¿Cuántos videos ha visto este usuario? ────────────────────────
        seen_key = f"seen:{user.id}"
        seen_raw = redis.smembers(seen_key)          # bytes en redis-py
        seen_ids = [int(x) for x in seen_raw] if seen_raw else []

        # Limpiar seen_ids que ya no existen en la BD para evitar feed vacío
        if seen_ids:
            existing_ids = set(
                Video.objects.filter(id__in=seen_ids).values_list('id', flat=True)
            )
            stale_ids = [sid for sid in seen_ids if sid not in existing_ids]
            if stale_ids:
                redis.srem(seen_key, *[str(s) for s in stale_ids])
                seen_ids = [sid for sid in seen_ids if sid in existing_ids]

        # ── 2. Cold start — usuario nuevo ────────────────────────────────────
        if len(seen_ids) < COLD_START_THRESHOLD:
            videos = _cold_start_videos(seen_ids, user=user)
            _mark_delivered(redis, user.id, videos)
            serializer = VideoZerializer(videos, many=True, context={'request': request})
            print("------", serializer.data)
            return Response({
                'mode': 'cold_start',
                'results': serializer.data,
            })

        # ── 3. Perfil de intereses del usuario ───────────────────────────────
        interests_key = f"profile:{user.id}"
        interests_raw = redis.hgetall(interests_key)
        # Decodificar bytes → str (redis-py sin decode_responses)
        interests = {
            k.decode() if isinstance(k, bytes) else k:
            v.decode() if isinstance(v, bytes) else v
            for k, v in interests_raw.items()
        }

        # Precalcular el máximo de interés para normalizar después
        scores = [float(v) for v in interests.values() if v]
        interests['__max__'] = str(max(scores)) if scores else '1.0'

        # ── 4. QuerySet base: videos recientes no vistos ──────────────────────
        privacy_q = _privacy_filter(user)
        base_qs = (
            Video.objects
            .filter(privacy_q, status='ready', is_safe=True, category__isnull=False)
            .select_related('category', 'stats')
            .exclude(id__in=seen_ids)
        )

        # ── 5. Sin perfil todavía → recientes ordenados, no cold start ───────
        if not scores:
            videos = list(base_qs.order_by('-created_at')[:FEED_PAGE_SIZE])
            if not videos:
                # Fallback: ignorar filtro de fecha si no hay nada nuevo
                videos = list(
                    Video.objects.filter(privacy_q, status='ready', is_safe=True)
                    .exclude(id__in=seen_ids)
                    .order_by('-created_at')[:FEED_PAGE_SIZE]
                )
            _mark_delivered(redis, user.id, videos)
            serializer = VideoZerializer(videos, many=True, context={'request': request})
            return Response({
                'mode': 'warming_up',
                'results': serializer.data,
            })

        # ── 6. Scoring SQL dinámico — inyectar interest_score por categoría ──
        whens = []
        for cat_id_str, score_str in interests.items():
            if cat_id_str.startswith('__'):
                continue
            try:
                whens.append(When(category_id=int(cat_id_str), then=Value(float(score_str))))
            except (ValueError, TypeError):
                continue

        candidates_qs = base_qs.annotate(
            interest_score=Case(
                *whens,
                default=Value(0.0),
                output_field=FloatField(),
            )
        ).order_by('-interest_score', '-created_at')

        # Incluimos también videos de fuera de la ventana de frescura si el usuario
        # tiene intereses fuertes (para no quedar sin contenido en apps pequeñas)
        top_candidates = list(candidates_qs[:CANDIDATE_POOL])

        if not top_candidates:
            # Fallback total: ignorar vistos (mejor repetir que mostrar nada)
            fallback = list(
                Video.objects.filter(privacy_q, status='ready', is_safe=True)
                .order_by('-created_at')[:FEED_PAGE_SIZE]
            )
            _mark_delivered(redis, user.id, fallback)
            serializer = VideoZerializer(fallback, many=True, context={'request': request})
            print(serializer.data, "-------------")
            return Response({
                'mode': 'fallback',
                'results': serializer.data,
            })

        # ── 7. Re-ranking híbrido en RAM ─────────────────────────────────────
        now = timezone.now()
        max_age_sec = FRESHNESS_WINDOW * 24 * 3600

        scored = [
            (_hybrid_score(v, interests, now, max_age_sec), v)
            for v in top_candidates
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        # ── 8. 80% explotación + 20% exploración (anti-burbuja) ──────────────
        exploit_n = max(1, int(FEED_PAGE_SIZE * EXPLOIT_RATIO))
        explore_n = FEED_PAGE_SIZE - exploit_n

        exploitation = [v for _, v in scored[:exploit_n]]

        # Pool de exploración: siguiente bloque de candidatos (no los top)
        explore_pool = [v for _, v in scored[exploit_n:exploit_n + 80]]
        exploration = random.sample(explore_pool, min(explore_n, len(explore_pool)))

        final_videos = exploitation + exploration
        random.shuffle(final_videos)

        _mark_delivered(redis, user.id, final_videos)
        serializer = VideoZerializer(final_videos, many=True, context={'request': request})
        print(serializer.data, "-------------")
        return Response({
            'mode': 'personalized',
            'results': serializer.data,
        })
