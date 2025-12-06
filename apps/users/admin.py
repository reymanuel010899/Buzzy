from django.contrib import admin
from .models import Country, User
# Register your models here.
class UserConfig(admin.ModelAdmin):
    list_display = ("id", "username")
    search_fields = ("id",)

admin.site.register(User, UserConfig)
admin.site.register(Country)