from django.contrib import admin
from .models import (
    Country, User, Availability, SocialAccount, UserSecurity, BuzzyPremium,
    FCMDevice, Trending, RecentSearch,
)
# Register your models here.
class UserConfig(admin.ModelAdmin):
    list_display = ("id", "username")
    search_fields = ("id",)

admin.site.register(User, UserConfig)
admin.site.register(Country)
admin.site.register(Availability)
admin.site.register(SocialAccount)
admin.site.register(UserSecurity)


@admin.register(FCMDevice)
class FCMDeviceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at', 'updated_at')
    search_fields = ('user__username', 'token')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Trending)
class TrendingAdmin(admin.ModelAdmin):
    list_display = ('term', 'count', 'updated_at')
    search_fields = ('term',)
    ordering = ('-count', '-updated_at')


@admin.register(RecentSearch)
class RecentSearchAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'term', 'created_at')
    search_fields = ('user__username', 'term')
    date_hierarchy = 'created_at'

@admin.register(BuzzyPremium)
class BuzzyPremiumAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'started_at', 'expires_at', 'is_active')
    list_filter = ('status',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('started_at',)

    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
