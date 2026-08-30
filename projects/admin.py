from django.contrib import admin
from django.contrib import messages
from django.db.models import Count
from django.core.management import call_command
from django.http import HttpResponse
import csv

from .models import (
    Project,
    ProjectAchievement,
    ProjectCaseStudy,
    ProjectCategory,
    ProjectComment,
    ProjectContribution,
    ProjectFeature,
    ProjectMedia,
    ProjectProgram,
    ProjectProgramParticipation,
    ProjectRepository,
    ProjectLike,
    ProjectRequest,
    ProjectRequestApplication,
    ProjectSave,
    ProjectType,
    ProjectUpdate,
    ProjectView,
    ProjectWritingSuggestion,
    Technology,
    Team, TeamInvitation, TeamMembership, TeamOpenRole,
)


@admin.register(ProjectType)
class ProjectTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'sort_order', 'requires_approval')
    list_filter = ('is_active', 'requires_advisor', 'requires_course', 'requires_organization', 'requires_approval')
    search_fields = ('name', 'code', 'description')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('sort_order', 'name')

    def get_readonly_fields(self, request, obj=None):
        return ('code',) if obj else ()

    def delete_queryset(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(ProjectProgram)
class ProjectProgramAdmin(admin.ModelAdmin):
    list_display = ('name', 'program_type', 'is_active', 'sort_order')
    list_filter = ('program_type', 'is_active')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('project_types',)


@admin.register(ProjectProgramParticipation)
class ProjectProgramParticipationAdmin(admin.ModelAdmin):
    list_display = ('project', 'program', 'year', 'application_status', 'result')
    list_filter = ('program', 'year', 'application_status')
    search_fields = ('project__title', 'program__name', 'award')


@admin.register(ProjectRepository)
class ProjectRepositoryAdmin(admin.ModelAdmin):
    list_display = ('project', 'repository_path', 'created_at')
    search_fields = ('project__title', 'repository_path')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ProjectRequest)
class ProjectRequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'teacher', 'project_type', 'status', 'deadline', 'created_at')
    list_filter = ('status', 'project_type', 'supervision_type')
    search_fields = ('title', 'teacher__username', 'teacher__first_name', 'teacher__last_name')
    filter_horizontal = ('categories', 'technologies')


@admin.register(ProjectRequestApplication)
class ProjectRequestApplicationAdmin(admin.ModelAdmin):
    list_display = ('project_request', 'student', 'status', 'reviewed_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('project_request__title', 'student__username', 'student__first_name', 'student__last_name')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at', 'withdrawn_at')


@admin.register(ProjectCaseStudy)
class ProjectCaseStudyAdmin(admin.ModelAdmin):
    list_display = ('project', 'updated_at')
    search_fields = ('project__title', 'summary', 'problem', 'solution')


@admin.register(ProjectWritingSuggestion)
class ProjectWritingSuggestionAdmin(admin.ModelAdmin):
    list_display = ('project', 'created_by', 'status', 'created_at', 'applied_at')
    list_filter = ('status', 'created_at')
    search_fields = ('project__title', 'created_by__username')
    readonly_fields = ('project', 'created_by', 'original_text', 'suggested_fields', 'status', 'created_at', 'applied_at')

    def has_add_permission(self, request):
        return False


@admin.register(ProjectMedia)
class ProjectMediaAdmin(admin.ModelAdmin):
    list_display = ('project', 'media_type', 'caption', 'is_cover', 'is_public', 'order')
    list_filter = ('media_type', 'is_cover', 'is_public')
    search_fields = ('project__title', 'caption', 'alt_text')


@admin.register(ProjectContribution)
class ProjectContributionAdmin(admin.ModelAdmin):
    list_display = ('project', 'user', 'role', 'verified_by_owner', 'verified_by_advisor', 'verified_at')
    list_filter = ('verified_by_owner', 'verified_by_advisor')
    search_fields = ('project__title', 'user__username', 'role', 'contribution_description')


@admin.register(ProjectAchievement)
class ProjectAchievementAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'achievement_type', 'organization', 'date', 'is_verified')
    list_filter = ('achievement_type', 'is_verified')
    search_fields = ('title', 'project__title', 'organization')


@admin.register(ProjectSave)
class ProjectSaveAdmin(admin.ModelAdmin):
    list_display = ('project', 'user', 'created_at')
    search_fields = ('project__title', 'user__username')


@admin.register(ProjectLike)
class ProjectLikeAdmin(admin.ModelAdmin):
    list_display = ('project', 'user', 'created_at')
    search_fields = ('project__title', 'user__username')


@admin.register(ProjectView)
class ProjectViewAdmin(admin.ModelAdmin):
    list_display = ('project', 'viewer', 'date_bucket', 'created_at')
    readonly_fields = ('project', 'viewer', 'session_hash', 'date_bucket', 'created_at')

    def has_add_permission(self, request):
        return False


@admin.register(ProjectFeature)
class ProjectFeatureAdmin(admin.ModelAdmin):
    list_display = ('project', 'is_active', 'starts_at', 'ends_at', 'sort_order')
    list_filter = ('is_active',)
    search_fields = ('project__title',)


@admin.register(ProjectCategory)
class ProjectCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'sort_order', 'usage_count', 'color', 'created_at')
    search_fields = ('name', 'description')
    list_filter = ('is_active', 'created_at')
    actions = ('deactivate_selected', 'merge_selected', 'export_csv', 'load_seed_data')

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_usage_count=Count('projects', distinct=True))

    @admin.display(ordering='_usage_count', description='Kullanım')
    def usage_count(self, obj):
        return obj._usage_count

    @admin.action(description='Seçilenleri pasife al')
    def deactivate_selected(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description='Seçilen tekrarları ilk kayıtta güvenle birleştir')
    def merge_selected(self, request, queryset):
        from .management.commands.seed_taxonomy import _merge_duplicate
        items = list(queryset.order_by('pk'))
        if len(items) < 2:
            self.message_user(request, 'Birleştirme için en az iki kayıt seçin.', messages.ERROR)
            return
        for duplicate in items[1:]:
            _merge_duplicate(duplicate, items[0])
        self.message_user(request, f'{len(items) - 1} kayıt pasifleştirilerek ilişkileri korundu.')

    @admin.action(description='CSV olarak dışa aktar')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="project-categories.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['name', 'slug', 'description', 'icon', 'color', 'is_active', 'sort_order'])
        for item in queryset:
            writer.writerow([item.name, item.slug, item.description, item.icon, item.color, item.is_active, item.sort_order])
        return response

    @admin.action(description='Güvenli başlangıç verilerini yükle')
    def load_seed_data(self, request, queryset):
        call_command('seed_taxonomy')
        self.message_user(request, 'Başlangıç verileri yüklendi.')


@admin.register(Technology)
class TechnologyAdmin(admin.ModelAdmin):
    list_display = ('name', 'group', 'is_active', 'sort_order', 'usage_count', 'created_at')
    search_fields = ('name', 'aliases', 'description')
    list_filter = ('group', 'is_active', 'created_at')
    actions = ('deactivate_selected', 'merge_selected', 'export_csv', 'load_seed_data')

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_usage_count=Count('projects', distinct=True))

    @admin.display(ordering='_usage_count', description='Kullanım')
    def usage_count(self, obj):
        return obj._usage_count

    @admin.action(description='Seçilenleri pasife al')
    def deactivate_selected(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description='Seçilen tekrarları ilk kayıtta güvenle birleştir')
    def merge_selected(self, request, queryset):
        return ProjectCategoryAdmin.merge_selected(self, request, queryset)

    @admin.action(description='CSV olarak dışa aktar')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="technologies.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['name', 'slug', 'group', 'description', 'official_url', 'aliases', 'is_active', 'sort_order'])
        for item in queryset:
            writer.writerow([item.name, item.slug, item.group, item.description, item.official_url, '|'.join(item.aliases), item.is_active, item.sort_order])
        return response

    @admin.action(description='Güvenli başlangıç verilerini yükle')
    def load_seed_data(self, request, queryset):
        call_command('seed_taxonomy')
        self.message_user(request, 'Başlangıç verileri yüklendi.')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'project_type', 'creation_source', 'created_by', 'advisor',
        'approval_status', 'development_status', 'visibility', 'created_at',
    )
    search_fields = ('title', 'created_by__username', 'advisor__username')
    list_filter = (
        'project_type', 'creation_source', 'approval_status',
        'development_status', 'visibility', 'categories', 'technologies',
    )
    filter_horizontal = ('categories', 'technologies', 'team')


@admin.register(ProjectUpdate)
class ProjectUpdateAdmin(admin.ModelAdmin):
    list_display = ('project', 'title', 'created_at')
    search_fields = ('title', 'description', 'version')


admin.site.register(Team)
admin.site.register(TeamMembership)
admin.site.register(TeamInvitation)
admin.site.register(TeamOpenRole)


@admin.register(ProjectComment)
class ProjectCommentAdmin(admin.ModelAdmin):
    list_display = ('project', 'author', 'parent', 'created_at')
    search_fields = ('content',)
