import uuid
import os
from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete
from django.utils import timezone
from datetime import timedelta
from django.db import models
from apps.users.models import User
from django.utils.text import slugify

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
    class FolderType(models.TextChoices):
        STANDARD = 'standard', 'Amigos'
        KNOWN = 'known', 'Conocidos'
        REQUEST = 'request', 'Solicitudes'
        HIDDEN = 'hidden', 'Ocultos'

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
    # Cada participante tiene su propio folder — independiente del otro
    folder_type_p1 = models.CharField(
        max_length=20,
        choices=FolderType.choices,
        default=FolderType.STANDARD,
    )
    folder_type_p2 = models.CharField(
        max_length=20,
        choices=FolderType.choices,
        default=FolderType.STANDARD,
    )

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

    def get_folder_for(self, user) -> str:
        """Retorna el folder_type personal del user en este chat."""
        if user == self.participant1:
            return self.folder_type_p1
        return self.folder_type_p2

    def set_folder_for(self, user, folder: str):
        """Guarda el folder_type personal del user sin hacer save()."""
        if user == self.participant1:
            self.folder_type_p1 = folder
        else:
            self.folder_type_p2 = folder

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
            ('story_reply', 'Respuesta a historia'),
        ],
        default='text'
    )
    file = models.FileField(upload_to='chats/media/%Y/%m/%d/', blank=True, null=True)
    story_uuid = models.CharField(max_length=50, blank=True, null=True)
    story_media_url = models.TextField(blank=True, null=True)
    story_audio_url = models.TextField(blank=True, null=True)
    is_deleted = models.BooleanField(default=False)
    deleted_for_all = models.BooleanField(default=False)  # "Eliminar para todos"
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    forwarded_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='forwards')
    is_edited = models.BooleanField(default=False)
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

    audio_track_url   = models.URLField(max_length=500, blank=True, null=True)
    audio_track_title = models.CharField(max_length=255, blank=True, null=True)
    audio_track_artist= models.CharField(max_length=255, blank=True, null=True)
    audio_volume_music= models.FloatField(default=0.8)
    audio_trim_start  = models.FloatField(default=0.0)
    audio_trim_end    = models.FloatField(blank=True, null=True)
    filter_css        = models.CharField(max_length=500, blank=True, null=True)
    text_layers       = models.JSONField(default=list, blank=True)
    sticker_layers    = models.JSONField(default=list, blank=True)
    location          = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def has_expired(self):
        return timezone.now() > self.created_at + timedelta(hours=24)

    def mark_expired(self):
        if self.has_expired() and self.is_active:
            self.delete()

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


class StoryReport(models.Model):
    REASON_CHOICES = [
        ("spam", "Spam"),
        ("violence", "Contenido violento"),
        ("nudity", "Desnudez o contenido sexual"),
        ("hate", "Discurso de odio"),
        ("other", "Otro"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("reviewed", "Revisado"),
        ("dismissed", "Descartado"),
    ]

    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="reports")
    reported_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="story_reports")
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("story", "reported_by")

    def __str__(self):
        return f"{self.reported_by.username} reportó Story {self.story.id} - {self.reason}"

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
    thumbnail = models.ImageField(
        upload_to='gifts/thumbnails/',
        blank=True, null=True,
        help_text="Frame extraído del video del regalo"
    )

    token_price = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    is_premium_exclusive = models.BooleanField(default=False, help_text="Solo usuarios Buzzy Premium pueden enviar/recibir este regalo")

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
    is_seen = models.BooleanField(default=False)
    vip_message = models.TextField(blank=True, default="")

    def total_tokens(self):
        return self.gift.token_price * self.quantity

    def __str__(self):
        return f"{self.sender} sent {self.gift.name} to Story {self.story.user.username}"


class VideoGift(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_gift_video')
    video = models.ForeignKey('Video', on_delete=models.CASCADE, related_name="received_gifts")
    gift = models.ForeignKey(GiftStory, on_delete=models.CASCADE, related_name="video_sent_gifts")
    gift_type = models.CharField(max_length=20)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="video_sent_gifts")
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    is_seen = models.BooleanField(default=False)
    vip_message = models.TextField(blank=True, default="")

    def total_tokens(self):
        return self.gift.token_price * self.quantity

    def __str__(self):
        return f"{self.sender} sent {self.gift.name} to Video {self.video.id}"

    

class UserGift(models.Model):
    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, blank=True)
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_user_gifts')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_user_gifts')
    gift = models.ForeignKey(GiftStory, on_delete=models.CASCADE, related_name='user_sent_gifts')
    gift_type = models.CharField(max_length=20)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    is_seen = models.BooleanField(default=False)
    vip_message = models.TextField(blank=True, default="")

    def total_tokens(self):
        return self.gift.token_price * self.quantity

    def __str__(self):
        return f"{self.sender} sent {self.gift.name} to {self.recipient.username}"


class Video(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Upload'),
        ('processing', 'AI Processing'),
        ('ready', 'Ready for Feed'),
        ('blocked', 'Blocked (Unsafe)'),
    ]

    PRIVACY_PUBLIC    = 'public'
    PRIVACY_FOLLOWERS = 'followers'
    PRIVACY_PRIVATE   = 'private'
    PRIVACY_CHOICES = [
        (PRIVACY_PUBLIC,    'Público'),
        (PRIVACY_FOLLOWERS, 'Solo seguidores'),
        (PRIVACY_PRIVATE,   'Privado'),
    ]

    uuid = models.CharField(max_length=32, default=full_uuid, unique=True, blank=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_reverce' ) 
    category = models.ForeignKey(Category, on_delete=models.CASCADE, blank=True, null=True)
    video_url = models.URLField(blank=True, null=True)
    video = models.FileField(upload_to='contenido/', blank=True, null=True)
    thumbnail_url = models.URLField(blank=True, null=True)
    audit_log = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True, null=True)
    tags = models.JSONField()
    media_type = models.CharField(
        max_length=10, 
        choices=[('video', 'Video'), ('image', 'Imagen')], 
        default='video'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_safe = models.BooleanField(default=False)
    safety_label = models.CharField(max_length=255, blank=True, null=True)
    transcript = models.TextField(blank=True, null=True)

    # ── Audio mixing ──────────────────────────────────────────────
    audio_track_url   = models.URLField(max_length=500, blank=True, null=True)
    volume_original   = models.FloatField(default=1.0)
    volume_music      = models.FloatField(default=0.8)
    audio_track_id    = models.CharField(max_length=64, blank=True, null=True)
    audio_track_title = models.CharField(max_length=255, blank=True, null=True)
    audio_track_artist= models.CharField(max_length=255, blank=True, null=True)
    audio_track_cover = models.URLField(max_length=500, blank=True, null=True)
    audio_trim_start  = models.FloatField(default=0.0)
    audio_trim_end    = models.FloatField(blank=True, null=True)

    privacy = models.CharField(
        max_length=10,
        choices=PRIVACY_CHOICES,
        default=PRIVACY_PUBLIC,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    duration = models.PositiveIntegerField(blank=True, null=True)



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
    PRIORITY_PLAN_CHOICES = [
        ('VIP', 'VIP'),
        ('PLUS', 'PLUS'),
        ('FRIEND', 'FRIEND'),
    ]
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies"
    )

    video_id = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='comernt_video_reverce')
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField(blank=True, default='')
    audio_file = models.FileField(upload_to='comments/audio/', null=True, blank=True)
    audio_duration = models.FloatField(null=True, blank=True)
    image_file = models.ImageField(upload_to='comments/images/', null=True, blank=True)
    is_priority_comment = models.BooleanField(default=False)
    priority_plan_name = models.CharField(max_length=20, choices=PRIORITY_PLAN_CHOICES, null=True, blank=True)
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

class SavedVideo(models.Model):
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_videos')
    video    = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='saved_by')
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'video')
        ordering = ['-saved_at']

    def __str__(self):
        return f"{self.user.username} saved video {self.video_id}"

class VideoStats(models.Model):
    """
    Aggregate engagement counters per video.
    All increments must use F() expressions to be atomic (race-condition safe).
    """
    video = models.OneToOneField(Video, on_delete=models.CASCADE, related_name='stats')
    starts = models.PositiveIntegerField(default=0)             # video_start events
    engagements = models.PositiveIntegerField(default=0)        # video_engagement events (3 s mark)
    valid_views = models.PositiveIntegerField(default=0)        # video_view_valid events (50 % mark)
    monetizable_views = models.PositiveIntegerField(default=0)  # video_view_monetizable (50% >= 10 s)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Video Stats'
        verbose_name_plural = 'Video Stats'

    def __str__(self):
        return f"Stats for Video {self.video_id}"

class Follower(models.Model):
    user_id = models.ForeignKey(User, related_name='following', on_delete=models.CASCADE)
    follower_user_id = models.ForeignKey(User, related_name='followers', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id.username} follow to {self.follower_user_id.username}"
    

class Notification(models.Model):
    class Type(models.TextChoices):
        FOLLOW       = 'follow',        'Follow'
        LIKE         = 'like',          'Like'
        COMMENT      = 'comment',       'Comment'
        COMMENT_REPLY = 'comment_reply','Comment Reply'
        PROFILE_VISIT = 'profile_visit','Profile Visit'
        STORY_LIKE   = 'story_like',    'Story Like'
        GIFT         = 'gift',          'Gift'
        MENTION      = 'mention',       'Mention'
        EARNING      = 'earning',       'Earning'
        WELCOME      = 'welcome',       'Welcome'

    # Recipient
    recipient   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    # Who triggered the notification
    actor       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notification_type = models.CharField(max_length=50, choices=Type.choices, default=Type.FOLLOW)
    # Optional references
    video       = models.ForeignKey('Video',   on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    comment     = models.ForeignKey('Comment', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    # Humanised text (optional override, generated on save if blank)
    message     = models.TextField(blank=True)
    is_read     = models.BooleanField(default=False, db_index=True)
    read_at     = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'created_at']),
        ]

    def __str__(self):
        return f"Notif({self.notification_type}) → {self.recipient_id}"
    
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

class AIStyle(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, null=True)
    icon_name = models.CharField(max_length=50, help_text="Nombre del icono en frontend, ej: ImageIcon")
    color_bg = models.CharField(max_length=100, help_text="Clases CSS para el fondo, ej: bg-blue-500/20")
    color_text = models.CharField(max_length=100, help_text="Clases CSS para el texto, ej: text-blue-400")
    color_border = models.CharField(max_length=100, help_text="Clases CSS para el borde hover, ej: hover:border-blue-500/50")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'AI Style'
        verbose_name_plural = 'AI Styles'

    def __str__(self):
        return self.name

class AITemplate(models.Model):
    style = models.ForeignKey(AIStyle, on_delete=models.CASCADE, related_name='templates')
    title = models.CharField(max_length=100)
    prompt = models.TextField()
    image_url = models.URLField(help_text="URL de la imagen de ejemplo (thumbnail)", blank=True, null=True)
    media_type = models.CharField(max_length=20, choices=[('image', 'Image'), ('video', 'Video')], default='image')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['style', 'order']
        verbose_name = 'AI Template'
        verbose_name_plural = 'AI Templates'

    def __str__(self):
        return f"{self.title} ({self.style.name})"

class AIGenerationHistory(models.Model):
    STATUS_CHOICES = [
        ('pending',    'Pendiente'),
        ('processing', 'Procesando'),
        ('completed',  'Completado'),
        ('failed',     'Fallido'),
    ]

    user            = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_history')
    prompt          = models.TextField()
    media_url       = models.URLField(max_length=500, blank=True, default='')
    media_type      = models.CharField(max_length=20, choices=[('image', 'Image'), ('video', 'Video')], default='image')
    style           = models.ForeignKey(AIStyle, on_delete=models.SET_NULL, null=True, blank=True)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    byteplus_task_id = models.CharField(max_length=255, blank=True, default='')
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'AI Generation History'
        verbose_name_plural = 'AI Generation Histories'

    def __str__(self):
        return f"{self.user.username} - {self.media_type} - {self.created_at}"


class AIPackage(models.Model):
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    videos_count = models.PositiveIntegerField(default=0, help_text="Videos que incluye el paquete")
    images_count = models.PositiveIntegerField(default=0, help_text="Imágenes que incluye el paquete")
    price = models.DecimalField(max_digits=6, decimal_places=2, help_text="Precio en USD")
    is_featured = models.BooleanField(default=False, help_text="Destacar este paquete")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'price']
        verbose_name = 'AI Package'
        verbose_name_plural = 'AI Packages'

    def __str__(self):
        return f"{self.name} — {self.videos_count}v + {self.images_count}i — ${self.price}"


class AIWallet(models.Model):
    """
    Billetera de créditos IA por usuario — completamente independiente
    de las suscripciones. Se recarga comprando paquetes con el wallet.
    """
    user = models.OneToOneField(
        'users.User',
        on_delete=models.CASCADE,
        related_name='ai_wallet',
    )
    video_credits = models.PositiveIntegerField(default=0, help_text="Créditos de video disponibles")
    image_credits = models.PositiveIntegerField(default=0, help_text="Créditos de imagen disponibles")
    total_videos_generated = models.PositiveIntegerField(default=0, help_text="Videos generados histórico")
    total_images_generated = models.PositiveIntegerField(default=0, help_text="Imágenes generadas histórico")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'AI Wallet'
        verbose_name_plural = 'AI Wallets'

    def __str__(self):
        return f"{self.user.username} — {self.video_credits}v / {self.image_credits}i"

    @classmethod
    def get_or_create_for(cls, user):
        wallet, _ = cls.objects.get_or_create(user=user)
        return wallet

    def can_generate_video(self, duration=6):
        import math
        cost = math.ceil(duration / 6)
        if self.video_credits < cost:
            available_secs = self.video_credits * 6
            return False, f"No tienes suficientes segundos disponibles. Tienes {available_secs}s y necesitas {duration}s."
        return True, "Ok"

    def can_generate_image(self):
        if self.image_credits <= 0:
            return False, "No tienes créditos de imagen disponibles. Recarga en Imagina IA."
        return True, "Ok"

    def consume_video(self, duration=6):
        import math
        cost = math.ceil(duration / 6)
        self.video_credits = max(0, self.video_credits - cost)
        self.total_videos_generated += 1
        self.save(update_fields=['video_credits', 'total_videos_generated', 'updated_at'])

    def consume_image(self):
        self.image_credits = max(0, self.image_credits - 1)
        self.total_images_generated += 1
        self.save(update_fields=['image_credits', 'total_images_generated', 'updated_at'])

    def add_credits(self, videos=0, images=0):
        self.video_credits += videos
        self.image_credits += images
        self.save(update_fields=['video_credits', 'image_credits', 'updated_at'])


class AudioTrack(models.Model):
    CATEGORY_CHOICES = [
        ('trending',   'Tendencias'),
        ('pop',        'Pop'),
        ('urban',      'Urban'),
        ('electronic', 'Electronic'),
        ('latin',      'Latin'),
        ('chill',      'Chill'),
    ]

    title      = models.CharField(max_length=255)
    artist     = models.CharField(max_length=255)
    cover      = models.ImageField(upload_to='audio_tracks/covers/', blank=True, null=True)
    audio_file = models.FileField(upload_to='audio_tracks/files/')
    duration_secs = models.PositiveIntegerField(default=0, help_text='Duración en segundos')
    category   = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='trending')
    is_active  = models.BooleanField(default=True)
    play_count = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Audio Track'
        verbose_name_plural = 'Audio Tracks'

    def __str__(self):
        return f"{self.title} — {self.artist}"

    @property
    def duration_display(self):
        m, s = divmod(self.duration_secs, 60)
        return f"{m}:{s:02d}"


class FavoriteTrack(models.Model):
    user  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorite_tracks')
    track = models.ForeignKey(AudioTrack, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'track')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} ♥ {self.track.title}"


# ── File cleanup signals ───────────────────────────────────────────────────────

def _delete_file(field):
    """Delete a FileField/ImageField file from storage, ignoring missing files."""
    try:
        if field and field.name:
            from django.core.files.storage import default_storage
            if default_storage.exists(field.name):
                default_storage.delete(field.name)
    except Exception:
        pass


@receiver(post_save, sender=GiftStory)
def generate_gift_thumbnail(sender, instance, created, **kwargs):
    """Extract first frame of gift video as thumbnail using ffmpeg."""
    if not instance.video or instance.thumbnail:
        return
    try:
        import subprocess, tempfile
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        video_path = instance.video.path
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name

        result = subprocess.run(
            ['ffmpeg', '-y', '-i', video_path, '-vframes', '1', '-q:v', '2', tmp_path],
            capture_output=True, timeout=30
        )
        if result.returncode == 0:
            with open(tmp_path, 'rb') as f:
                thumb_name = f'gifts/thumbnails/{instance.slug}.jpg'
                saved_path = default_storage.save(thumb_name, ContentFile(f.read()))
                GiftStory.objects.filter(pk=instance.pk).update(thumbnail=saved_path)

        os.unlink(tmp_path)
    except Exception:
        pass


@receiver(post_delete, sender=StoryMedia)
def delete_story_media_file(sender, instance, **kwargs):
    _delete_file(instance.file)


@receiver(post_delete, sender=Story)
def delete_story_sticker_files(sender, instance, **kwargs):
    """When a story is deleted, remove any uploaded sticker files from storage."""
    from django.core.files.storage import default_storage
    for layer in (instance.sticker_layers or []):
        if layer.get("kind") in ("image", "video"):
            src = layer.get("src", "")
            if src and src.startswith("http"):
                # Extract relative path from absolute URL
                from urllib.parse import urlparse
                from django.conf import settings
                parsed = urlparse(src)
                media_url = getattr(settings, "MEDIA_URL", "/media/")
                if parsed.path.startswith(media_url):
                    rel_path = parsed.path[len(media_url):]
                    try:
                        if default_storage.exists(rel_path):
                            default_storage.delete(rel_path)
                    except Exception:
                        pass


@receiver(post_delete, sender=Video)
def delete_video_files(sender, instance, **kwargs):
    _delete_file(instance.video)
