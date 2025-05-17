from django.contrib import admin
from .models import Event, News

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'event_type', 'start_date', 'end_date', 'is_active')
    search_fields = ('title', 'description')
    list_filter = ('event_type', 'is_active')

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'author', 'created_at', 'is_published')
    search_fields = ('title', 'content')
    list_filter = ('category', 'is_published')
