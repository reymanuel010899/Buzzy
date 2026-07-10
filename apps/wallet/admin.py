from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from apps.wallet.models import (
    CurrencyModel, TransactionModel, WalletModel,
    TokenPackage, BankAccount, GlobalSettings,
    VideoEarningsDaily, CreatorEarningsPeriod,
    BonusCampaign, CreatorBonus, MonetizableViewLog,
)

admin.site.register(CurrencyModel)
admin.site.register(WalletModel)
admin.site.register(TransactionModel)
admin.site.register(TokenPackage)
admin.site.register(BankAccount)
admin.site.register(GlobalSettings)
admin.site.register(VideoEarningsDaily)


@admin.register(MonetizableViewLog)
class MonetizableViewLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'video', 'date')
    list_filter = ('date',)
    search_fields = ('user__username',)
    date_hierarchy = 'date'


@admin.register(CreatorEarningsPeriod)
class CreatorEarningsPeriodAdmin(admin.ModelAdmin):
    list_display = ('creator', 'week_start', 'week_end', 'monetizable_views', 'net_amount_display', 'status', 'paid_at', 'approve_button')
    list_filter = ('status', 'week_start')
    search_fields = ('creator__username',)
    readonly_fields = ('creator', 'week_start', 'week_end', 'monetizable_views', 'rate_per_1000', 'gross_amount', 'net_amount', 'created_at', 'paid_at')
    ordering = ('-week_start', 'status')

    def net_amount_display(self, obj):
        return f"${obj.net_amount} USD"
    net_amount_display.short_description = "Neto"

    def approve_button(self, obj):
        if obj.status == 'pending':
            return format_html(
                '<a class="button" href="/admin/wallet/creatorearningsperiod/{}/approve/">✅ Aprobar</a>',
                obj.pk
            )
        return obj.get_status_display()
    approve_button.short_description = "Acción"

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom = [
            path('<int:period_id>/approve/', self.admin_site.admin_view(self.approve_view), name='approve-earning-period'),
        ]
        return custom + urls

    def approve_view(self, request, period_id):
        from django.http import HttpResponseRedirect
        from django.contrib import messages
        from apps.wallet.tasks import approve_earning_period

        approve_earning_period.delay(period_id)
        messages.success(request, f"Periodo #{period_id} enviado a procesar. El wallet se acreditará en segundos.")
        return HttpResponseRedirect('/admin/wallet/creatorearningsperiod/')


@admin.register(BonusCampaign)
class BonusCampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'follower_threshold', 'capacity', 'winners_count_display',
                    'is_full_display', 'duration_months', 'gift_fee_pct',
                    'view_rate_per_1000', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(_wc=Count('bonuses'))

    def winners_count_display(self, obj):
        return getattr(obj, '_wc', obj.winners_count)
    winners_count_display.short_description = 'Ganadores'
    winners_count_display.admin_order_field = '_wc'

    def is_full_display(self, obj):
        return obj.is_full
    is_full_display.boolean = True
    is_full_display.short_description = 'Lleno'


@admin.register(CreatorBonus)
class CreatorBonusAdmin(admin.ModelAdmin):
    list_display = ('user', 'campaign', 'started_at', 'expires_at', 'is_active_display',
                    'gift_fee_pct', 'view_rate_per_1000', 'follower_count_at_win')
    list_filter = ('campaign',)
    search_fields = ('user__username', 'campaign__name')
    readonly_fields = ('user', 'campaign', 'started_at', 'expires_at', 'gift_fee_pct',
                       'view_rate_per_1000', 'follower_count_at_win', 'created_at')
    ordering = ('-created_at',)

    def is_active_display(self, obj):
        return obj.is_active
    is_active_display.boolean = True
    is_active_display.short_description = 'Activo'

    def has_add_permission(self, request):
        # Los bonos se ganan automáticamente, no se crean a mano.
        return False
