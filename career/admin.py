from django.contrib import admin

from .models import CollaborationRequest, MentorshipProfile, MentorshipRequest, MentorshipReview, Opportunity


@admin.register(CollaborationRequest)
class CollaborationRequestAdmin(admin.ModelAdmin):
    list_display = ('tracking_number', 'organization', 'request_type', 'status', 'email_verified_at', 'created_at')
    list_filter = ('status', 'request_type', 'publication_channel', 'email_verified_at')
    search_fields = ('tracking_number', 'organization', 'title', 'contact_name')
    filter_horizontal = ('categories', 'technologies')
    readonly_fields = (
        'tracking_number', 'email_verified_at', 'consent_at', 'project_request',
        'opportunity', 'reviewed_by', 'reviewed_at', 'created_at', 'updated_at',
    )


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'opportunity_type', 'approval_status', 'deadline', 'is_active')
    list_filter = ('approval_status', 'opportunity_type', 'work_mode', 'is_active')
    search_fields = ('title', 'organization', 'description')
    filter_horizontal = ('technologies',)
    readonly_fields = ('slug', 'approved_by', 'approved_at', 'created_at', 'updated_at')


@admin.register(MentorshipProfile)
class MentorshipProfileAdmin(admin.ModelAdmin):
    list_display = ('alumni', 'is_available', 'monthly_capacity', 'preferred_contact_method')
    list_filter = ('is_available', 'preferred_contact_method')
    filter_horizontal = ('mentoring_topics',)


@admin.register(MentorshipRequest)
class MentorshipRequestAdmin(admin.ModelAdmin):
    list_display = ('student', 'mentor', 'status', 'created_at', 'responded_at')
    list_filter = ('status', 'created_at')
    search_fields = ('student__username', 'mentor__alumni__full_name', 'goal')
    readonly_fields = ('created_at', 'updated_at', 'responded_at', 'completed_at')


@admin.register(MentorshipReview)
class MentorshipReviewAdmin(admin.ModelAdmin):
    list_display = ('mentorship_request', 'rating', 'created_at')
    readonly_fields = ('created_at',)
