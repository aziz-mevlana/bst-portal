from django.contrib import admin
from .models import Article, NewsKeyword

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'category', 'is_approved', 'is_featured', 'date')
    list_filter = ('is_approved', 'is_featured', 'category', 'date')
    search_fields = ('title', 'summary', 'source')
    prepopulated_fields = {'slug': ('title',)}

@admin.register(NewsKeyword)
class NewsKeywordAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'is_active', 'created_at')
    list_editable = ('is_active',)
