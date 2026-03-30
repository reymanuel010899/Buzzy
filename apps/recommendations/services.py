from .utils import get_redis_client

# Pesos sugeridos para cada tipo de interacción (Ajustables)
ACTION_WEIGHTS = {
    'view': 0.1,
    'like': 0.5,
    'share': 1.0,
    'comment': 0.3,
    'gift': 1.5,
}

def record_video_view(user_id, video_id):
    """
    (A1) Guarda en un Redis SET los IDs de los videos que el usuario ya vio.
    Para llamarlo: record_video_view(request.user.id, video.id)
    """
    if not user_id or not video_id:
        return
    
    redis_client = get_redis_client()
    key = f"seen:{user_id}"
    
    # Agregar el video al set de vistos
    redis_client.sadd(key, str(video_id))
    
    # Opcional: Caducidad (TTL) de 30 días para no llenar la RAM infinitamente
    redis_client.expire(key, 30 * 24 * 60 * 60)

def update_user_interests(user_id, category_id, action_type):
    """
    (A2) Incrementa el peso de una categoría en un Redis HASH según la acción del usuario.
    Para llamarlo: update_user_interests(request.user.id, video.category.id, 'like')
    """
    if not user_id or not category_id:
        return
        
    weight = ACTION_WEIGHTS.get(action_type, 0.1)
    
    redis_client = get_redis_client()
    key = f"profile:{user_id}"
    
    # Incrementar el score (peso) de esta categoría. HINCRBYFLOAT suma atómicamente.
    redis_client.hincrbyfloat(key, str(category_id), weight)
