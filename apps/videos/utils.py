from django.db.models import Q
from .models import ChatRoom
def get_or_create_chat(user1, user2):
    """Obtiene o crea chat entre dos usuarios"""
    chat, created = ChatRoom.objects.get_or_create(
        participant1=min(user1, user2),
        participant2=max(user1, user2)
    )
    return chat

def get_user_chats(user):
    """Chats del usuario ordenados por última actividad"""
    return ChatRoom.objects.filter(
        Q(participant1=user) | Q(participant2=user)
    ).select_related('participant1', 'participant2').order_by('-updated_at')