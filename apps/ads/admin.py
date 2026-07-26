from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import (
    AdCampaign, AdAudience, AdCreative, AdBudget,
    AdAnalytics, AdImpression, AdDailyFrequency, AdReview, AdsConfig,
)


class AdAudienceInline(admin.StackedInline):
    model = AdAudience
    extra = 0


class AdCreativeInline(admin.StackedInline):
    model = AdCreative
    extra = 0


class AdBudgetInline(admin.StackedInline):
    model = AdBudget
    extra = 0


class AdReviewInline(admin.StackedInline):
    model = AdReview
    extra = 0
    readonly_fields = ['submitted_at']


@admin.register(AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    list_display  = ['name', 'user', 'kind', 'objective', 'status_badge', 'budget_info', 'spent_pct', 'created_at']
    list_filter   = ['status', 'objective', 'created_at']
    search_fields = ['name', 'user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    autocomplete_fields = ['promoted_video']
    inlines = [AdAudienceInline, AdCreativeInline, AdBudgetInline, AdReviewInline]
    actions = ['approve_campaigns', 'reject_campaigns', 'pause_campaigns', 'activate_campaigns']

    def kind(self, obj):
        if obj.promoted_video_id:
            return format_html(
                '<span style="background:#2563eb;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px">📹 Boost</span>'
            )
        return format_html(
            '<span style="background:#6b7280;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px">Externo</span>'
        )
    kind.short_description = 'Tipo'

    def status_badge(self, obj):
        colors = {
            'DRAFT':     '#6b7280',
            'IN_REVIEW': '#f59e0b',
            'ACTIVE':    '#10b981',
            'PAUSED':    '#f97316',
            'REJECTED':  '#ef4444',
            'COMPLETED': '#8b5cf6',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">{}</span>',
            color, obj.status
        )
    status_badge.short_description = 'Status'

    def budget_info(self, obj):
        bud = getattr(obj, 'budget', None)
        if not bud:
            return '—'
        return f'${bud.total_budget} / ${bud.daily_budget}/day'
    budget_info.short_description = 'Budget'

    def spent_pct(self, obj):
        bud = getattr(obj, 'budget', None)
        if not bud or not bud.total_budget:
            return '0%'
        pct = round(float(bud.spent_amount / bud.total_budget) * 100, 1)
        return format_html(
            '<div style="width:80px;background:#374151;border-radius:4px;overflow:hidden">'
            '<div style="width:{}%;background:#10b981;height:8px"></div></div> {}%',
            min(pct, 100), pct
        )
    spent_pct.short_description = 'Spent'

    @admin.action(description='✅ Approve selected campaigns')
    def approve_campaigns(self, request, queryset):
        for campaign in queryset.filter(status='IN_REVIEW'):
            campaign.status = 'ACTIVE'
            campaign.save()
            review = getattr(campaign, 'review', None)
            if review:
                review.decision    = 'APPROVED'
                review.reviewed_at = timezone.now()
                review.reviewed_by = request.user
                review.save()
        self.message_user(request, f'{queryset.count()} campaign(s) approved.')

    @admin.action(description='❌ Reject selected campaigns')
    def reject_campaigns(self, request, queryset):
        for campaign in queryset.filter(status='IN_REVIEW'):
            campaign.status = 'REJECTED'
            campaign.rejection_reason = 'Rejected by moderator.'
            campaign.save()
            review = getattr(campaign, 'review', None)
            if review:
                review.decision         = 'REJECTED'
                review.rejection_reason = 'Rejected by moderator.'
                review.reviewed_at      = timezone.now()
                review.reviewed_by      = request.user
                review.save()
        self.message_user(request, f'{queryset.count()} campaign(s) rejected.')

    @admin.action(description='⏸ Pause selected campaigns')
    def pause_campaigns(self, request, queryset):
        queryset.filter(status='ACTIVE').update(status='PAUSED')

    @admin.action(description='▶️ Activate selected campaigns')
    def activate_campaigns(self, request, queryset):
        queryset.filter(status__in=['PAUSED', 'IN_REVIEW']).update(status='ACTIVE')


@admin.register(AdReview)
class AdReviewAdmin(admin.ModelAdmin):
    list_display  = ['campaign', 'decision', 'submitted_at', 'reviewed_at', 'reviewed_by']
    list_filter   = ['decision']
    search_fields = ['campaign__name']
    readonly_fields = ['submitted_at']
    actions = ['quick_approve', 'quick_reject']

    @admin.action(description='✅ Quick approve')
    def quick_approve(self, request, queryset):
        for review in queryset.filter(decision='PENDING'):
            review.decision    = 'APPROVED'
            review.reviewed_at = timezone.now()
            review.reviewed_by = request.user
            review.save()
            review.campaign.status = 'ACTIVE'
            review.campaign.save()

    @admin.action(description='❌ Quick reject')
    def quick_reject(self, request, queryset):
        for review in queryset.filter(decision='PENDING'):
            review.decision         = 'REJECTED'
            review.rejection_reason = 'Rejected by moderator.'
            review.reviewed_at      = timezone.now()
            review.reviewed_by      = request.user
            review.save()
            review.campaign.status = 'REJECTED'
            review.campaign.save()


@admin.register(AdAnalytics)
class AdAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'date', 'impressions', 'clicks', 'ctr_display']
    list_filter  = ['date']

    def ctr_display(self, obj):
        return f'{obj.ctr}%'
    ctr_display.short_description = 'CTR'


admin.site.register(AdAudience)
admin.site.register(AdCreative)
admin.site.register(AdBudget)
admin.site.register(AdImpression)
admin.site.register(AdDailyFrequency)

@admin.register(AdsConfig)
class AdsConfigAdmin(admin.ModelAdmin):
    list_display = ('cpm_rate', 'cpc_rate', 'ctr_estimate')

    def has_add_permission(self, request):
        return not AdsConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
