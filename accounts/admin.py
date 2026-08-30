from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    CommunicationPreference, CommunityRegistration, ConsentRecord, DataSubjectRequest,
    PortfolioCertificate, Profile, UserModerationAction, UserReport,
    WebsiteModerationHistory,
)


@admin.register(CommunityRegistration)
class CommunityRegistrationAdmin(admin.ModelAdmin):
    list_display = ('user', 'wants_to_share', 'status', 'reviewed_by', 'created_at')
    list_filter = ('wants_to_share', 'status', 'created_at')
    search_fields = ('user__username', 'user__email', 'introduction', 'motivation', 'content_plan', 'reference_url')
    readonly_fields = (
        'user', 'introduction', 'motivation', 'wants_to_share', 'content_plan',
        'reference_url', 'additional_notes', 'status', 'reviewer_note', 'reviewed_by',
        'reviewed_at', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_type', 'account_status', 'institutional_email_verified_at', 'public_slug', 'is_portfolio_public', 'student_number')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'student_number')
    list_filter = ('user_type', 'account_status', 'institutional_email_verified_at', 'teacher_title', 'department', 'is_portfolio_public', 'is_featured')
    readonly_fields = ('institutional_email_verified_at', 'academic_approved_at', 'academic_approved_by')


@admin.register(PortfolioCertificate)
class PortfolioCertificateAdmin(admin.ModelAdmin):
    list_display = ('title', 'profile', 'issuer', 'issued_at', 'is_public')
    list_filter = ('is_public', 'issuer')
    search_fields = ('title', 'issuer', 'profile__user__username')


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'consent_type', 'accepted', 'text_version', 'created_at')
    list_filter = ('consent_type', 'accepted', 'text_version')
    readonly_fields = ('user', 'consent_type', 'accepted', 'text_version', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommunicationPreference)
class CommunicationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'email_announcements', 'email_project_updates', 'email_events', 'updated_at')


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'request_type', 'status', 'created_at', 'completed_at')
    list_filter = ('request_type', 'status')
    search_fields = ('user__username', 'user__email', 'explanation')
    readonly_fields = ('user', 'request_type', 'explanation', 'created_at')


class ProfileInline(admin.StackedInline):
    model = Profile
    fk_name = 'user'
    can_delete = False
    extra = 0


class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_active', 'get_user_type', 'get_account_status')
    list_filter = ('is_active', 'profile__user_type', 'profile__account_status', 'profile__institutional_email_verified_at')
    
    def get_user_type(self, obj):
        if hasattr(obj, 'profile'):
            return obj.profile.get_user_type_display()
        return '-'
    get_user_type.short_description = 'User Type'

    @admin.display(description='Hesap durumu')
    def get_account_status(self, obj):
        return obj.profile.get_account_status_display() if hasattr(obj, 'profile') else '-'


@admin.register(UserModerationAction)
class UserModerationActionAdmin(admin.ModelAdmin):
    list_display = ('user', 'action_type', 'performed_by', 'created_at', 'expires_at')
    list_filter = ('action_type', 'created_at')
    search_fields = ('user__username', 'performed_by__username', 'reason', 'description')
    readonly_fields = ('user', 'action_type', 'reason', 'description', 'performed_by', 'starts_at', 'expires_at', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserReport)
class UserReportAdmin(admin.ModelAdmin):
    list_display = ('reported_user', 'reason', 'status', 'reporter', 'created_at')
    list_filter = ('status', 'reason', 'created_at')
    search_fields = ('reported_user__username', 'reporter__username', 'description')
    readonly_fields = ('reporter', 'reported_user', 'related_content', 'reason', 'description', 'created_at')


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(WebsiteModerationHistory)
class WebsiteModerationHistoryAdmin(admin.ModelAdmin):
    list_display = ('profile', 'status', 'performed_by', 'created_at')
    readonly_fields = ('profile', 'website_url', 'status', 'reason', 'description', 'performed_by', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
