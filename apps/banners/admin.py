from django.contrib import admin
from django.utils.html import format_html
from django.urls import path
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.db.models import Count, Q
from .models import UserGroup, GroupRequirement, UserGroupMembership, BuzzyBanner, BannerView, BannerInteraction
from .tasks import sync_groups_task


class GroupRequirementInline(admin.TabularInline):
    model = GroupRequirement
    extra = 1


class UserGroupMembershipInline(admin.TabularInline):
    model = UserGroupMembership
    extra = 0
    readonly_fields = ('joined_at',)


@admin.register(UserGroup)
class UserGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_auto', 'member_count', 'created_at', 'sync_button')
    list_filter = ('is_auto',)
    search_fields = ('name',)
    inlines = [GroupRequirementInline, UserGroupMembershipInline]

    def member_count(self, obj):
        return obj.memberships.count()
    member_count.short_description = 'Miembros'

    def sync_button(self, obj):
        return format_html(
            '<a class="button" href="{}sync/">🔄 Sync</a>',
            f'/admin/banners/usergroup/{obj.pk}/'
        )
    sync_button.short_description = 'Acción'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('sync-all/', self.admin_site.admin_view(self.sync_all_view), name='banners_sync_all'),
            path('<int:pk>/sync/', self.admin_site.admin_view(self.sync_one_view), name='banners_sync_one'),
        ]
        return custom + urls

    def sync_all_view(self, request):
        # Lanza tarea Celery en background
        sync_groups_task.delay()
        self.message_user(request, "Sincronización lanzada en background via Celery.", messages.SUCCESS)
        return HttpResponseRedirect('/admin/banners/usergroup/')

    def sync_one_view(self, request, pk):
        group = UserGroup.objects.get(pk=pk)
        sync_groups_task.delay(group_id=pk)
        self.message_user(request, f"Sincronización de '{group.name}' lanzada en background.", messages.SUCCESS)
        return HttpResponseRedirect('/admin/banners/usergroup/')

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['sync_all_url'] = 'sync-all/'
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(BuzzyBanner)
class BuzzyBannerAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'type', 'effect', 'target', 'priority',
        'is_active', 'color_preview', 'stats_summary', 'expires_at', 'created_at'
    )
    list_filter = ('type', 'effect', 'target', 'is_active')
    search_fields = ('title', 'message')
    readonly_fields = ('created_at', 'color_preview', 'stats_panel')
    fieldsets = (
        ('Contenido', {
            'fields': ('title', 'message', 'type', 'effect', 'priority')
        }),
        ('Destino', {
            'fields': ('target', 'user', 'group')
        }),
        ('Estilo Visual', {
            'fields': ('background_color', 'text_color', 'accent_color', 'color_preview', 'image')
        }),
        ('Call to Action', {
            'fields': ('action_url', 'action_label'),
        }),
        ('Opciones por Efecto', {
            'fields': ('reveal_content', 'countdown_label'),
            'classes': ('collapse',)
        }),
        ('Control', {
            'fields': ('is_active', 'expires_at', 'created_at')
        }),
        ('Analytics', {
            'fields': ('stats_panel',),
            'classes': ('collapse',),
        }),
    )

    def color_preview(self, obj):
        return format_html(
            '<div style="width:120px;height:30px;border-radius:6px;background:{};display:flex;'
            'align-items:center;justify-content:center;">'
            '<span style="color:{};font-size:11px;font-weight:bold;">Preview</span></div>',
            obj.background_color, obj.text_color
        )
    color_preview.short_description = 'Preview color'

    def stats_summary(self, obj):
        views = obj.views.count()
        clicks = obj.interactions.filter(action='click').count()
        dismissals = obj.interactions.filter(action='dismiss').count()
        ctr = f"{(clicks/views*100):.1f}%" if views else "—"
        return format_html(
            '👁 {} &nbsp; 🖱 {} &nbsp; CTR {}',
            views, clicks, ctr
        )
    stats_summary.short_description = 'Stats'

    def stats_panel(self, obj):
        interactions = obj.interactions.values('action').annotate(total=Count('id'))
        rows = "".join(
            f"<tr><td style='padding:4px 12px'>{i['action']}</td>"
            f"<td style='padding:4px 12px;font-weight:bold'>{i['total']}</td></tr>"
            for i in interactions
        )
        views = obj.views.count()
        clicks = obj.interactions.filter(action='click').count()
        ctr = f"{(clicks/views*100):.1f}%" if views else "—"
        return format_html(
            '<table style="border-collapse:collapse;font-size:13px">'
            '<tr><th style="padding:4px 12px;text-align:left">Acción</th>'
            '<th style="padding:4px 12px;text-align:left">Total</th></tr>'
            '{}'
            '<tr style="border-top:1px solid #ccc"><td style="padding:4px 12px"><b>Vistas únicas</b></td>'
            '<td style="padding:4px 12px;font-weight:bold">{}</td></tr>'
            '<tr><td style="padding:4px 12px"><b>CTR</b></td>'
            '<td style="padding:4px 12px;font-weight:bold">{}</td></tr>'
            '</table>',
            format_html(rows), views, ctr
        )
    stats_panel.short_description = 'Analytics detallado'


@admin.register(BannerView)
class BannerViewAdmin(admin.ModelAdmin):
    list_display = ('user', 'banner', 'seen_at', 'dismissed')
    list_filter = ('dismissed',)
    search_fields = ('user__username', 'banner__title')
    readonly_fields = ('seen_at',)


@admin.register(BannerInteraction)
class BannerInteractionAdmin(admin.ModelAdmin):
    list_display = ('user', 'banner', 'action', 'created_at')
    list_filter = ('action',)
    search_fields = ('user__username', 'banner__title')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
