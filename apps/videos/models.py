import uuid
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.utils import timezone
from datetime import timedelta
from django.db import models
from apps.users.models import User
from django.utils.text import slugify
from django.contrib.postgres import indexes 

def full_uuid():
    return str(uuid.uuid4()).replace("-", "")

def gift_upload_path(instance, filename):
    return f"gifts/{instance.slug}/{filename}"
def chat_uuid():
    return str(uuid.uuid4())[:8]

class ChatRoom(models.Model):
    """
    Sala de chat 1:1 entre dos usuarios (estilo WhatsApp/IG)
    """
    uuid = models.CharField(max_length=8, default=chat_uuid, unique=True, db_index=True)
    participant1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_rooms_as_p1')
    participant2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_rooms_as_p2')
    initiator = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='initiated_chats',
        help_text="Usuario que inició la conversación (normalmente quien siguió primero)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Cache para performance
    last_message_preview = models.CharField(max_length=255, blank=True, null=True)
    last_message_time = models.DateTimeField(null=True, blank=True)
    unread_count_p1 = models.PositiveIntegerField(default=0)
    unread_count_p2 = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('participant1', 'participant2')
        indexes = [
            models.Index(fields=['participant1', 'updated_at']),
            models.Index(fields=['participant2', 'updated_at']),
            models.Index(fields=['last_message_time']),
        ]
        verbose_name = 'Chat Room'
        verbose_name_plural = 'Chat Rooms'

    def __str__(self):
        return f"Chat {self.uuid} - {self.participant1.username} ↔ {self.participant2.username}"
    
    def get_other_participant(self, user):
        """Retorna el otro participante (no el usuario actual)"""
        return self.participant1 if user == self.participant2 else self.participant2
    
    def reset_unread_count(self, user):
        """Reset contadores de no leídos para un usuario"""
        if user == self.participant1:
            self.unread_count_p1 = 0
        else:
            self.unread_count_p2 = 0
        self.save(update_fields=['unread_count_p1', 'unread_count_p2'])

class Message(models.Model):
    """
    Mensaje individual con todo lo premium (reacciones, delete, etc)
    """
    uuid = models.CharField(max_length=8, default=chat_uuid, unique=True, db_index=True)
    chat_room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField()  # Texto del mensaje
    message_type = models.CharField(
        max_length=20,
        choices=[
            ('text', 'Texto'),
            ('image', 'Imagen'),
            ('video', 'Video'),
            ('audio', 'Audio'), # Added 'audio' choice
            ('voice', 'Nota de voz'),
            ('gif', 'GIF'),
            ('file', 'Archivo'),
            ('document', 'Documento'),
            ('contact', 'Contacto'),
            ('poll', 'Encuesta'),
            ('event', 'Evento'),
            ('sticker', 'Sticker'),
        ],
        default='text'
    )
    file = models.FileField(upload_to='chats/media/%Y/%m/%d/', blank=True, null=True)
    is_deleted = models.BooleanField(default=False)
    deleted_for_all = models.BooleanField(default=False)  # "Eliminar para todos"
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['chat_room', 'created_at']),  # Orden cronológico
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['chat_room', 'is_deleted']),
        ]
        ordering = ['created_at']
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'

    def __str__(self):
        return f"Msg {self.uuid} - {self.sender.username}: {self.content[:30]}"
    
    def delete_for_all(self):
        """Eliminar para todos (estilo WhatsApp)"""
        self.deleted_for_all = True
        self.content = "[Este mensaje fue eliminado]"
        self.save()
    
    def soft_delete(self, user):
        """Eliminar solo para mí"""
        self.is_deleted = True
        self.save()

class MessageReaction(models.Model):
    """
    Reacciones a mensajes (❤️ 😂 🔥 etc)
    """
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reaction = models.CharField(max_length=10)  # ❤️ 😂 🔥 etc
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user', 'reaction')
        verbose_name = 'Message Reaction'
        verbose_name_plural = 'Message Reactions'

    def __str__(self):
        return f"{self.user.username} {self.reaction} → Msg {self.message.uuid}"

class UserOnlineStatus(models.Model):
    """
    Estado online/offline en tiempo real (WebSocket)
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='online_status')
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(auto_now=True)
    device_token = models.CharField(max_length=255, blank=True, null=True)  # Para push notifications

    class Meta:
        verbose_name = 'User Online Status'
        verbose_name_plural = 'User Online Status'

    def __str__(self):
        return f"{self.user.username} - {'🟢 Online' if self.is_online else '🔴 Offline'}"
    
    def update_activity(self):
        """Actualizar actividad (llamar desde WebSocket)"""
        self.last_activity = timezone.now()
        self.is_online = True
        self.save(update_fields=['is_online', 'last_activity', 'last_seen'])

class TypingStatus(models.Model):
    """
    'Usuario está escribiendo...' (WebSocket en tiempo real)
    """
    chat_room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='typing_status')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_typing = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('chat_room', 'user')
        verbose_name = 'Typing Status'
        verbose_name_plural = 'Typing Status'

    def __str__(self):
        status = "escribiendo..." if self.is_typing else "no escribiendo"
        return f"{self.user.username} {status} en {self.chat_room.uuid}"
    
class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey('self', related_name='subcategories', on_delete=models.SET_NULL, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True) 
    updated_at = models.DateTimeField(auto_now=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    seo_title = models.CharField(max_length=255, blank=True, null=True) 
    seo_description = models.TextField(blank=True, null=True) 

    def save(self, *args, **kwargs):
        if not self.slug: 
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Category {self.id} - {self.name}"

    class Meta:
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['slug']),
        ]


class Story(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="stories")
    
    text = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)  
    created_at = models.DateTimeField(auto_now_add=True)

    def has_expired(self):
        return timezone.now() > self.created_at + timedelta(hours=24)

    def mark_expired(self):
        if self.has_expired() and self.is_active:
            self.is_active = False
            self.save()

    def total_views(self):
        return self.story_views.count()

    def __str__(self):
        return f"Story {self.id} - User {self.user.username}"
    

class StoryMedia(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, blank=True)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="media")
    file = models.FileField(upload_to="stories/media/")  # Imagen o Video
    type = models.CharField(max_length=20, choices=[
        ("image", "Image"),
        ("video", "Video"),
    ])

    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Media {self.id} - Story {self.story.id}"

class StoryView(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="story_views")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("story", "user")

    def __str__(self):
        return f"{self.user.username} viewed Story {self.story.id}"
    
class StoryLike(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="story_likes")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    liked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("story", "user")

    def __str__(self):
        return f"{self.user.username} liked Story {self.story.id}"

    @classmethod
    def total_likes(cls, story):
        return cls.objects.filter(story=story).count()

    @classmethod
    def is_liked(cls, story, user):
        return cls.objects.filter(story=story, user=user).exists()

    def unlike(self):
        self.delete()

class GiftStory(models.Model):
    name = models.CharField(max_length=100) 
    slug = models.SlugField(unique=True)     
    emoji = models.CharField(max_length=100, blank=True, null=True)
    color_premiun = models.CharField(max_length=100, blank=True, null=True)
    video = models.FileField(
        upload_to=gift_upload_path,
        help_text="Video MP4 con fondo transparente si es posible"
    )

    token_price = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
          
class StoryGift(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_gift_story')
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="received_gifts")
    gift = models.ForeignKey(GiftStory, on_delete=models.CASCADE, related_name="sent_gifts")
    gift_type = models.CharField(max_length=20)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_gifts")
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    def total_tokens(self):
        return self.gift.token_price * self.quantity

    def __str__(self):
        return f"{self.sender} sent {self.gift.name} to Story {self.story.user.username}"
    

class Video(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, blank=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_reverce' ) 
    category = models.ForeignKey(Category, on_delete=models.CASCADE, blank=True, null=True)
    video_url = models.URLField()
    video = models.FileField(upload_to='contenido/', blank=True, null=True)
    thumbnail_url = models.URLField()
    description = models.TextField(blank=True, null=True)
    tags = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    duration = models.PositiveIntegerField()


    def get_count_view(self):
        return self.video_reverce.count()
    
    def get_count_comment(self):
        return self.comernt_video_reverce.count()

    def get_count_like(self):
        return self.like_video_reverce.count()

    def __str__(self):
        return f"Video {self.id} - {self.description[:50]}"

    class Meta:
        verbose_name = 'Video'
        verbose_name_plural = 'Videos'

class Comment(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, null=True, blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies"
    )

    video_id = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='comernt_video_reverce')
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comentario {self.id} - {self.content[:50]}"

class Like(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, null=True, blank=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE) 
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='like_video_reverce')
    created_at = models.DateTimeField(auto_now_add=True) 
    def __str__(self):
        return f"Like {self.id} - Video {self.video_id.id}"
    
class View(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, null=True, blank=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='video_reverce')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"View {self.id} - Video {self.video_id.id}"

class Follower(models.Model):
    user_id = models.ForeignKey(User, related_name='following', on_delete=models.CASCADE)
    follower_user_id = models.ForeignKey(User, related_name='followers', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id.username} follow to {self.follower_user_id.username}"
    

class Notification(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE) 
    type = models.CharField(max_length=50) 
    message = models.TextField() 
    read_status = models.BooleanField(default=False)  
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notificación {self.id} - {self.type}"
    
class Hashtag(models.Model):
    name = models.CharField(max_length=100, unique=True) 
    videos_count = models.PositiveIntegerField(default=0)  

    def __str__(self):
        return f"Hashtag {self.id} - {self.name}"
    
class VideoHashtag(models.Model):
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE) 
    hashtag_id = models.ForeignKey('Hashtag', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('video_id', 'hashtag_id') 

    def __str__(self):
        return f"Video {self.video_id.video_id} - Hashtag {self.hashtag_id.name}"

@receiver(post_save, sender=Follower)
def create_chat_on_follow(sender, instance, created, **kwargs):
    print("--------------------")
    if not created:
        return

    follower = instance.user_id          # quien sigue (A)
    following = instance.follower_user_id    # quien es seguido (B)

    # Ordenamos para mantener consistencia en participant1/participant2
    p1, p2 = sorted([follower, following], key=lambda u: u.id)

    chat, is_new = ChatRoom.objects.get_or_create(
        participant1=p1,
        participant2=p2,
        defaults={
            'initiator': follower  # ← ¡Importante! El que sigue es el iniciador
        }
    )