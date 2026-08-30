from django.contrib import admin

from .models import ChatCache, KnowledgeSource, UnansweredQuestion


@admin.register(KnowledgeSource)
class KnowledgeSourceAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'audience', 'is_active', 'updated_at')
    list_filter = ('category', 'audience', 'is_active')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ChatCache)
class ChatCacheAdmin(admin.ModelAdmin):
    list_display = ('question', 'audience_key', 'hit_count', 'last_used_at', 'is_active')
    list_filter = ('audience_key', 'is_active')
    readonly_fields = ('question_hash', 'created_at', 'last_used_at')
    search_fields = ('question',)


@admin.register(UnansweredQuestion)
class UnansweredQuestionAdmin(admin.ModelAdmin):
    list_display = ('safe_summary', 'ask_count', 'roles', 'last_asked_at', 'resolved_at')
    list_filter = ('resolved_at',)
    search_fields = ('safe_summary',)
    readonly_fields = ('question_hash', 'safe_summary', 'ask_count', 'roles', 'first_asked_at', 'last_asked_at')
