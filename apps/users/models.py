from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from .manayers import CustomUserManager
from django.core.exceptions import ValidationError
# Create your models here.

class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)

    def __str__(self):
        return self.name
    
class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    birthdate = models.DateField(null=True, blank=True)
    profile_picture = models.ImageField(upload_to='media/profile_pics/', default='media/profile_pics/avatar.webp',  null=True, blank=True)
    profile_video = models.FileField(upload_to='media/profile_videos/', null=True, blank=True)
    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.username
    
    def all_followers(self):
        return self.followers.all()
    
    def all_followed(self):
        return self.following.all()
    
    def total_social_followers(self):
        """Suma los seguidores de todas las redes sociales conectadas."""
        return sum(account.followers_count for account in self.social_accounts.all())

    def all_likes(self):
        total = sum(like.like_video_reverce.count() for like in self.user_reverce.all())
        return total

    def all_comments(self):
        total = sum(comment.comernt_video_reverce.count() for comment in self.user_reverce.all())
        return total

    def all_views(self):
        total = sum(video.video_reverce.count() for video in self.user_reverce.all())
        return total
    

class Trending(models.Model):
    term = models.CharField(max_length=255, unique=True)
    count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.term

    class Meta:
        verbose_name = 'Trending'
        verbose_name_plural = 'Trending'
        ordering = ['-count', '-updated_at']

class RecentSearch(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recent_searches')
    term = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} searched for {self.term}"

    class Meta:
        verbose_name = 'Recent Search'
        verbose_name_plural = 'Recent Searches'
        ordering = ['-created_at']
        unique_together = ('user', 'term')

class Availability(models.Model):
    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='availabilities'
    )
    
    day_of_week = models.PositiveSmallIntegerField(choices=DAYS_OF_WEEK)
    
    start_time = models.TimeField()
    end_time = models.TimeField()
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['user', 'day_of_week', 'start_time', 'end_time']
        verbose_name_plural = "Availabilities"

    def clean(self):
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValidationError("La hora de fin debe ser posterior a la de inicio.")

    def __str__(self):
        return f"{self.user.username} - {self.get_day_of_week_display()} ({self.start_time} - {self.end_time})"


class SocialAccount(models.Model):
    PLATFORM_CHOICES = [
        ('instagram', 'Instagram'),
        ('tiktok', 'TikTok'),
        ('facebook', 'Facebook'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='social_accounts'
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    platform_user_id = models.CharField(max_length=255)
    platform_username = models.CharField(max_length=255, blank=True)
    # Tokens cifrados en producción — aquí TextField simple para demo local
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True)
    followers_count = models.PositiveIntegerField(default=0)
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'platform')
        verbose_name = 'Social Account'
        verbose_name_plural = 'Social Accounts'

    def __str__(self):
        return f"{self.user.username} → {self.platform} (@{self.platform_username})"