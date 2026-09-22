from django.contrib import admin

from .models import CapstoneCheckpoint, CapstoneEnrollment, CapstoneProject, CapstoneTask, CapstoneTerm


@admin.register(CapstoneTerm)
class CapstoneTermAdmin(admin.ModelAdmin):
    list_display = ('academic_year', 'semester', 'starts_at', 'midterm_at', 'final_at', 'is_active')
    list_filter = ('semester', 'is_active')


@admin.register(CapstoneEnrollment)
class CapstoneEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'term', 'is_active', 'approved_by', 'created_at')
    list_filter = ('term', 'is_active')
    search_fields = ('student__username', 'student__first_name', 'student__last_name')


@admin.register(CapstoneProject)
class CapstoneProjectAdmin(admin.ModelAdmin):
    list_display = ('project', 'term', 'created_at')
    list_filter = ('term',)


@admin.register(CapstoneCheckpoint)
class CapstoneCheckpointAdmin(admin.ModelAdmin):
    list_display = ('capstone_project', 'kind', 'due_at')
    list_filter = ('kind',)


@admin.register(CapstoneTask)
class CapstoneTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'capstone_project', 'checkpoint', 'created_by', 'due_at', 'required_file_count')
    list_filter = ('checkpoint__kind', 'due_at')
    search_fields = ('title', 'instructions', 'capstone_project__project__title')
