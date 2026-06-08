from django.contrib import admin
from .models import Country, User, Availability, SocialAccount, UserSecurity, BuzzyPremium
# Register your models here.
class UserConfig(admin.ModelAdmin):
    list_display = ("id", "username")
    search_fields = ("id",)

admin.site.register(User, UserConfig)
admin.site.register(Country)
admin.site.register(Availability)
admin.site.register(SocialAccount)
admin.site.register(UserSecurity)

@admin.register(BuzzyPremium)
class BuzzyPremiumAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'started_at', 'expires_at', 'is_active')
    list_filter = ('status',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('started_at',)

    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
