from django.db import models
from apps.users.models import User
from django.utils.text import slugify

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

class Video(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE,  )  # Referencia al usuario que sube el video
    category = models.ForeignKey(Category, on_delete=models.CASCADE, blank=True, null=True)
    video_url = models.URLField()  # URL o ruta del archivo de video
    video = models.FileField(upload_to='contenido/', blank=True, null=True)
    thumbnail_url = models.URLField()  # URL o ruta de la miniatura del video
    description = models.TextField()  # Descripción del video
    tags = models.JSONField()  # Etiquetas asociadas al video (puede ser una lista)
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha de subida del video
    updated_at = models.DateTimeField(auto_now=True)  # Fecha de la última modificación
    duration = models.PositiveIntegerField()  # Duración del video en segundos


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
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='comernt_video_reverce')
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comentario {self.id} - {self.content[:50]}"

class Like(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE) 
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='like_video_reverce')
    created_at = models.DateTimeField(auto_now_add=True) 
    def __str__(self):
        return f"Like {self.id} - Video {self.video_id.id}"
    
class View(models.Model):
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
        return f"Follower {self.id} - {self.user_id.username} follows {self.follower_user_id.username}"
    
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
    