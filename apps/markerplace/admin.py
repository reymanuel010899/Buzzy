from django.contrib import admin
from . import models


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "price", "category", "stock", "status", "created_at")
    list_filter = ("status", "category")
    search_fields = ("name", "description")
