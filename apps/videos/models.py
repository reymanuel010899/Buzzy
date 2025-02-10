from django.db import models
from apps.users.models import User

class Video(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)  # Referencia al usuario que sube el video
    video_url = models.URLField()  # URL o ruta del archivo de video
    thumbnail_url = models.URLField()  # URL o ruta de la miniatura del video
    description = models.TextField()  # Descripción del video
    tags = models.JSONField()  # Etiquetas asociadas al video (puede ser una lista)
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha de subida del video
    updated_at = models.DateTimeField(auto_now=True)  # Fecha de la última modificación
    duration = models.PositiveIntegerField()  # Duración del video en segundos
    likes_count = models.PositiveIntegerField(default=0)  # Número de "me gusta" del video
    comments_count = models.PositiveIntegerField(default=0)  # Número de comentarios en el video

    def __str__(self):
        return f"Video {self.id} - {self.description[:50]}"

    class Meta:
        verbose_name = 'Video'
        verbose_name_plural = 'Videos'

class Comment(models.Model):
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE)  # ID del video al que pertenece el comentario
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)  # ID del usuario que hizo el comentario
    content = models.TextField()  # Contenido del comentario
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha en que se hizo el comentario

    def __str__(self):
        return f"Comentario {self.id} - {self.content[:50]}"

class Like(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)  # ID del usuario que dio el like
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE)  # ID del video que recibió el like
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha en que el like fue dado

    def __str__(self):
        return f"Like {self.id} - Video {self.video_id.video_id}"
    
class View(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha en que el like fue dado

    def __str__(self):
        return f"View {self.id} - Video {self.video_id.video_id}"

class Follower(models.Model):
    user_id = models.ForeignKey(User, related_name='following', on_delete=models.CASCADE)  # ID del usuario que sigue a otro
    follower_user_id = models.ForeignKey(User, related_name='followers', on_delete=models.CASCADE)  # ID del usuario que está siendo seguido
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha en que se empezó a seguir a otro usuario

    def __str__(self):
        return f"Follower {self.id} - {self.user_id.username} follows {self.follower_user_id.username}"
    
class Notification(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)  # ID del usuario que recibe la notificación
    type = models.CharField(max_length=50)  # Tipo de notificación (e.g., comentario, like, nuevo seguidor)
    message = models.TextField()  # Mensaje de la notificación
    read_status = models.BooleanField(default=False)  # Estado de lectura de la notificación (leída/no leída)
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha de la notificación

    def __str__(self):
        return f"Notificación {self.id} - {self.type}"
    
class Hashtag(models.Model):
    name = models.CharField(max_length=100, unique=True)  # Nombre del hashtag (e.g., #foryou, #trending)
    videos_count = models.PositiveIntegerField(default=0)  # Número de videos que usan este hashtag

    def __str__(self):
        return f"Hashtag {self.id} - {self.name}"
    
class VideoHashtag(models.Model):
    video_id = models.ForeignKey(Video, on_delete=models.CASCADE)  # Referencia al video
    hashtag_id = models.ForeignKey('Hashtag', on_delete=models.CASCADE)  # Referencia al hashtag

    class Meta:
        unique_together = ('video_id', 'hashtag_id')  # Asegura que no haya duplicados en la relación

    def __str__(self):
        return f"Video {self.video_id.video_id} - Hashtag {self.hashtag_id.name}"
    