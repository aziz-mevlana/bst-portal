from django.contrib import admin
from .models import Article, NewsKeyword

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'date')

@admin.register(NewsKeyword)
class NewsKeywordAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'is_active', 'created_at')
    list_editable = ('is_active',)
