from django.utils import timezone
from datetime import timedelta
from django.db import models
from apps.users.models import User
from django.utils.text import slugify
import uuid

def full_uuid():
    return str(uuid.uuid4()).replace("-", "")

def gift_upload_path(instance, filename):
    # Ejemplo: gifts/rocket/rocket.mp4
    return f"gifts/{instance.slug}/{filename}"

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
    
    text = models.TextField(blank=True, null=True)  # texto opcional
    is_active = models.BooleanField(default=True)   # si ya expiró
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
    user_id = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_reverce' )  # Referencia al usuario que sube el video
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
    