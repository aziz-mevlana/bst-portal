from django.contrib import admin

from .models import (
    CapstoneCheckpoint, CapstoneCheckpointEvaluation, CapstoneEnrollment,
    CapstoneProject, CapstoneProposal, CapstoneTask, CapstoneTerm,
)


class ReadOnlyAcademicRecordAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CapstoneTerm)
class CapstoneTermAdmin(admin.ModelAdmin):
    list_display = ('academic_year', 'semester', 'starts_at', 'midterm_at', 'final_at', 'is_active')
    list_filter = ('semester', 'is_active')


@admin.register(CapstoneEnrollment)
class CapstoneEnrollmentAdmin(ReadOnlyAcademicRecordAdmin):
    list_display = ('student', 'term', 'advisor', 'is_active', 'approved_by', 'created_at')
    list_filter = ('term', 'is_active')
    search_fields = ('student__username', 'student__first_name', 'student__last_name')


@admin.register(CapstoneProject)
class CapstoneProjectAdmin(ReadOnlyAcademicRecordAdmin):
    list_display = ('project', 'term', 'completed_at', 'completed_by', 'created_at')
    list_filter = ('term',)


@admin.register(CapstoneCheckpoint)
class CapstoneCheckpointAdmin(ReadOnlyAcademicRecordAdmin):
    list_display = ('capstone_project', 'kind', 'due_at')
    list_filter = ('kind',)
    exclude = ('max_score',)


@admin.register(CapstoneTask)
class CapstoneTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'capstone_project', 'checkpoint', 'created_by', 'due_at', 'required_file_count')
    list_filter = ('checkpoint__kind', 'due_at')
    search_fields = ('title', 'instructions', 'capstone_project__project__title')


@admin.register(CapstoneProposal)
class CapstoneProposalAdmin(ReadOnlyAcademicRecordAdmin):
    list_display = ('title', 'student', 'requested_advisor', 'term', 'status', 'created_at')
    list_filter = ('term', 'status')


@admin.register(CapstoneCheckpointEvaluation)
class CapstoneCheckpointEvaluationAdmin(ReadOnlyAcademicRecordAdmin):
    list_display = ('checkpoint', 'evaluated_by', 'evaluated_at')
    exclude = ('score',)
