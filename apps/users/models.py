from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from .manayers import CustomUserManager
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
    profile_picture = models.ImageField(upload_to='media/profile_pics/', default='profile_pics/avatar.webp',  null=True, blank=True)
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
    
    def all_likes(self):
        total = sum(like.like_video_reverce.count() for like in self.user_reverce.all())
        return total

    def all_comments(self):
        total = sum(comment.comernt_video_reverce.count() for comment in self.user_reverce.all())
        return total

    def all_views(self):
        total = sum(video.video_reverce.count() for video in self.user_reverce.all())
        return total
    
