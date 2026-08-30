from django.contrib import admin

from .models import AnalyticsEvent, AuditLog, FooterLink, Notification


@admin.register(FooterLink)
class FooterLinkAdmin(admin.ModelAdmin):
    list_display = ('label', 'section', 'url', 'sort_order', 'is_active', 'open_new_tab')
    list_editable = ('sort_order', 'is_active', 'open_new_tab')
    list_filter = ('section', 'is_active')
    search_fields = ('label', 'url')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'action', 'actor', 'target_type', 'target_id')
    list_filter = ('action', 'target_type', 'created_at')
    search_fields = ('actor__username', 'target_id', 'metadata')
    readonly_fields = ('actor', 'action', 'target_type', 'target_id', 'metadata', 'client_hash', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'recipient', 'notification_type', 'read_at')
    list_filter = ('notification_type', 'read_at', 'created_at')
    search_fields = ('recipient__username', 'message')
    readonly_fields = ('created_at',)


@admin.register(AnalyticsEvent)
class AnalyticsEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'event_type', 'target_type', 'target_id', 'succeeded')
    list_filter = ('event_type', 'succeeded', 'date_bucket')
    readonly_fields = ('event_type', 'target_type', 'target_id', 'visitor_hash', 'succeeded', 'metadata', 'date_bucket', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
