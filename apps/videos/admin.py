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
admin.site.register(models.StoryReport)
@admin.register(models.GiftStory)
class GiftStoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'emoji', 'token_price', 'is_premium_exclusive', 'is_active')
    list_filter = ('is_premium_exclusive', 'is_active')
    list_editable = ('is_premium_exclusive', 'is_active')
admin.site.register(models.TypingStatus)
admin.site.register(models.UserOnlineStatus)
admin.site.register(models.MessageReaction)
admin.site.register(models.Message)
admin.site.register(models.ChatRoom)
admin.site.register(models.AIStyle)
admin.site.register(models.AIGenerationHistory)
admin.site.register(models.AIPackage)


@admin.register(models.AIWallet)
class AIWalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'video_credits', 'image_credits', 'total_videos_generated', 'total_images_generated', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('total_videos_generated', 'total_images_generated', 'updated_at', 'created_at')
admin.site.register(models.Category)

from django.utils.html import format_html

@admin.register(models.AudioTrack)
class AudioTrackAdmin(admin.ModelAdmin):
    list_display  = ('cover_preview', 'title', 'artist', 'category', 'duration_display', 'play_count', 'is_active', 'created_at')
    list_filter   = ('category', 'is_active')
    search_fields = ('title', 'artist')
    list_editable = ('is_active',)
    ordering      = ('-created_at',)
    readonly_fields = ('play_count', 'created_at', 'cover_preview', 'audio_preview')

    fieldsets = (
        ('Info', {
            'fields': ('title', 'artist', 'category', 'duration_secs', 'is_active')
        }),
        ('Archivos', {
            'fields': ('cover', 'cover_preview', 'audio_file', 'audio_preview')
        }),
        ('Stats', {
            'fields': ('play_count', 'created_at')
        }),
    )

    def cover_preview(self, obj):
        if obj.cover:
            return format_html('<img src="{}" style="width:48px;height:48px;object-fit:cover;border-radius:8px"/>', obj.cover.url)
        return '—'
    cover_preview.short_description = 'Cover'

    def audio_preview(self, obj):
        if obj.audio_file:
            return format_html(
                '<audio controls style="width:100%;max-width:400px">'
                '<source src="{}" type="audio/mpeg">'
                '</audio>', obj.audio_file.url
            )
        return '—'
    audio_preview.short_description = 'Preview'

    def duration_display(self, obj):
        return obj.duration_display
    duration_display.short_description = 'Duración'
