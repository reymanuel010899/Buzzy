from django.contrib import admin
from . import  models
# Register your models here.
class StoryConfig(admin.ModelAdmin):
    list_display = ("id",)
    search_fields = ("id",)

class FollowerConfig(admin.ModelAdmin):
    list_display = ("user_id", "follower_user_id")
    search_fields = ("id",)

class GiftConfig(admin.ModelAdmin):
    list_display = ("id", "uuid")
    search_fields = ("uuid",)

admin.site.register(models.Video)
admin.site.register(models.Comment, GiftConfig)
admin.site.register(models.Like)
admin.site.register(models.Follower, FollowerConfig)
admin.site.register(models.Notification)
admin.site.register(models.Hashtag)
admin.site.register(models.VideoHashtag)
admin.site.register(models.View)

admin.site.register(models.StoryMedia, StoryConfig)
admin.site.register(models.StoryView)
admin.site.register(models.Story, StoryConfig)
admin.site.register(models.StoryLike)
admin.site.register(models.StoryGift, GiftConfig)
admin.site.register(models.GiftStory)
admin.site.register(models.TypingStatus)
admin.site.register(models.UserOnlineStatus)
admin.site.register(models.MessageReaction)
admin.site.register(models.Message)
admin.site.register(models.ChatRoom)
admin.site.register(models.AIStyle)
admin.site.register(models.AIGenerationHistory)
admin.site.register(models.Category)