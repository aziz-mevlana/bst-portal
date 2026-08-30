from django.contrib import admin
from .models import Alumni, AlumniRegistrationRequest, WorkExperience

@admin.register(Alumni)
class AlumniAdmin(admin.ModelAdmin):
    list_display = ('user', 'graduation_year', 'current_position', 'company', 'experience_level')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'company')
    list_filter = ('graduation_year', 'experience_level')

@admin.register(WorkExperience)
class WorkExperienceAdmin(admin.ModelAdmin):
    list_display = ('person', 'company', 'position', 'start_date', 'end_date', 'is_current')
    search_fields = ('company', 'position')


@admin.register(AlumniRegistrationRequest)
class AlumniRegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'graduation_year', 'status', 'created_at')
    list_filter = ('status', 'graduation_year')
    search_fields = ('full_name', 'email', 'student_number')
