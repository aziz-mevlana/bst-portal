from django.contrib import admin

from .models import Event, EventRegistration


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'start_date', 'location', 'allow_registration', 'capacity', 'is_active')
    list_filter = ('event_type', 'allow_registration', 'is_active', 'certificate_enabled')
    search_fields = ('title', 'description', 'location')


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = ('event', 'user', 'status', 'checked_in_at', 'certificate_eligible', 'created_at')
    list_filter = ('status', 'certificate_eligible', 'created_at')
    search_fields = ('event__title', 'user__username', 'user__first_name', 'user__last_name')
    readonly_fields = ('checkin_token', 'checked_in_at', 'created_at', 'updated_at')
