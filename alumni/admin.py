from django.contrib import admin
from .models import SkillTag, Alumni, WorkExperience

@admin.register(SkillTag)
class SkillTagAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Alumni)
class AlumniAdmin(admin.ModelAdmin):
    list_display = ('user', 'graduation_year', 'current_position', 'company', 'experience_level')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'company')
    list_filter = ('graduation_year', 'experience_level')

@admin.register(WorkExperience)
class WorkExperienceAdmin(admin.ModelAdmin):
    list_display = ('person', 'company', 'position', 'start_date', 'end_date', 'is_current')
    search_fields = ('company', 'position')
