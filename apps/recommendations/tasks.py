from celery import shared_task
from .utils import get_redis_client

@shared_task
def decay_user_interests():
    """
    (C) Tarea periódica de Mantenimiento Celery: Interest Decay
    Disminuye gradualmente (multiplicando por 0.95) los intereses de todos los usuarios
    una vez al día. Garantiza que los temas abandonados dejen de ser recomendados.
    """
    redis_client = get_redis_client()
    
    cursor = '0'
    processed = 0
    # Usando SCAN en lugar de KEYS para procesar millones sin bloquear Redis (Non-blocking)
    while cursor != 0:
        cursor, keys = redis_client.scan(cursor=cursor, match='profile:*', count=5000)
        
        for key in keys:
            interests = redis_client.hgetall(key)
            for cat_id, score_str in interests.items():
                current_score = float(score_str)
                new_score = current_score * 0.95
                
                # Para evitar hashes infinitos y liberar RAM, borramos intereses casi nulos
                if new_score < 0.05:
                    redis_client.hdel(key, cat_id)
                else:
                    redis_client.hset(key, cat_id, new_score)
            processed += 1
            
    return f"Interest decay completed for {processed} profiles"
