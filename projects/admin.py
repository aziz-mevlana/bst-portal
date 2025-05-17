from django.contrib import admin
from .models import Project, ProjectUpdate, ProjectComment

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'student', 'supervisor', 'status', 'start_date', 'deadline')
    search_fields = ('title', 'student__username', 'supervisor__username')
    list_filter = ('status',)

@admin.register(ProjectUpdate)
class ProjectUpdateAdmin(admin.ModelAdmin):
    list_display = ('project', 'title', 'created_by', 'created_at')
    search_fields = ('title', 'content')

@admin.register(ProjectComment)
class ProjectCommentAdmin(admin.ModelAdmin):
    list_display = ('project', 'author', 'created_at')
    search_fields = ('content',)
