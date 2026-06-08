from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from apps.wallet.models import (
    CurrencyModel, TransactionModel, WalletModel,
    TokenPackage, BankAccount, GlobalSettings,
    VideoEarningsDaily, CreatorEarningsPeriod,
)

admin.site.register(CurrencyModel)
admin.site.register(WalletModel)
admin.site.register(TransactionModel)
admin.site.register(TokenPackage)
admin.site.register(BankAccount)
admin.site.register(GlobalSettings)
admin.site.register(VideoEarningsDaily)


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
