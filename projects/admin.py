from django.contrib import admin
from .models import Respons, ResponsUpdate, Comment, Request, ProjectCategory, Technology


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'teacher', 'created_at')
    search_fields = ('title', 'teacher__username')


@admin.register(ProjectCategory)
class ProjectCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'created_at')
    search_fields = ('name',)
    list_filter = ('created_at',)


@admin.register(Technology)
class TechnologyAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'created_at')
    search_fields = ('name',)
    list_filter = ('created_at',)


@admin.register(Respons)
class ResponsAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'advisor', 'status', 'created_at')
    search_fields = ('title', 'created_by__username', 'advisor__username')
    list_filter = ('status', 'categories', 'technologies')
    filter_horizontal = ('categories', 'technologies', 'team')


@admin.register(ResponsUpdate)
class ResponsUpdateAdmin(admin.ModelAdmin):
    list_display = ('respons', 'which_respons', 'updated_at')
    search_fields = ('which_respons', 'note')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('respons', 'author', 'created_at')
    search_fields = ('content',)
