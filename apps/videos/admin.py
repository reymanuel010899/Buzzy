from django.contrib import admin
from . import  models
# Register your models here.
admin.site.register(models.Video)
admin.site.register(models.Comment)
admin.site.register(models.Like)
admin.site.register(models.Follower)
admin.site.register(models.Notification)
admin.site.register(models.Hashtag)
admin.site.register(models.VideoHashtag)
admin.site.register(models.View)
# admin.site.register(models.Video)