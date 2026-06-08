from django.contrib import admin
from .models import ReferralToken, ReferralProfile


@admin.register(ReferralToken)
class ReferralTokenAdmin(admin.ModelAdmin):
    list_display = ('owner', 'token_short', 'is_active', 'used_by', 'expires_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('owner__username', 'used_by__username', 'token')
    readonly_fields = ('token', 'created_at', 'expires_at')

    def token_short(self, obj):
        return f"{obj.token[:16]}..."
    token_short.short_description = 'Token'


@admin.register(ReferralProfile)
class ReferralProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_invitados')
    search_fields = ('user__username',)
