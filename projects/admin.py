from django.contrib import admin
from .models import Project, ProjectUpdate, ProjectComment, ProjectRequest, ProjectCategory, Technology


@admin.register(ProjectRequest)
class ProjectRequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'teacher', 'created_at')
    search_fields = ('title', 'teacher__username')


@admin.register(ProjectCategory)
class ProjectCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'created_at')
    search_fields = ('name',)
    list_filter = ('created_at',)


@admin.register(Technology)
class TechnologyAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'icon', 'created_at')
    search_fields = ('name',)
    list_filter = ('created_at',)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'advisor', 'created_at', 'status')
    search_fields = ('title', 'created_by__username', 'advisor__username')
    list_filter = ('categories', 'technologies', 'created_at')
    filter_horizontal = ('categories', 'technologies', 'team')


@admin.register(ProjectUpdate)
class ProjectUpdateAdmin(admin.ModelAdmin):
    list_display = ('project', 'title', 'created_at')
    search_fields = ('title', 'note')


@admin.register(ProjectComment)
class ProjectCommentAdmin(admin.ModelAdmin):
    list_display = ('project', 'author', 'created_at')
    search_fields = ('content',)
