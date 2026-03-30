import redis
from django.conf import settings
from django_redis import get_redis_connection

def get_redis_client():
    """
    Retorna la conexión a Redis. 
    Usa django-redis por defecto, con un fallback a redis-py directo.
    """
    try:
        # Intenta usar la conexión de django-redis configurada en settings.CACHES['default']
        client = get_redis_connection("default")
        return client
    except Exception:
        # Fallback si no está configurado explícitamente en CACHES
        redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/1')
        # decode_responses=True asegura que devuelva strings y no bytes
        return redis.Redis.from_url(redis_url, decode_responses=True)
