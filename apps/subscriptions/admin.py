from django.contrib import admin
from . import models


class SubscriptionBenefitInline(admin.TabularInline):
    """Edita los beneficios (y su orden) directamente desde el plan."""
    model = models.SubscriptionBenefit
    extra = 1
    fields = ('order', 'benefit_type', 'limit', 'description')
    ordering = ('order', 'id')


@admin.register(models.SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    inlines = [SubscriptionBenefitInline]
    list_display = ('name', 'price', 'is_active')


@admin.register(models.SubscriptionBenefit)
class SubscriptionBenefitAdmin(admin.ModelAdmin):
    list_display = ('plan', 'order', 'benefit_type', 'limit', 'description')
    list_editable = ('order',)          # editar el orden inline desde la lista
    list_filter = ('plan', 'benefit_type')
    ordering = ('plan', 'order', 'id')


admin.site.register(models.UserSubscription)


@admin.register(models.CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display = ('uuid', 'caller', 'callee', 'call_type', 'status',
                    'allowed_seconds', 'consumed_seconds', 'started_at', 'ended_at')
    list_filter = ('call_type', 'status')
    search_fields = ('caller__username', 'callee__username', 'channel_name')
    readonly_fields = ('uuid', 'started_at')
    date_hierarchy = 'started_at'