from django import forms

from .models import Alumni, WorkExperience
from accounts.validators import validate_public_website


class AlumniProfileForm(forms.ModelForm):
    class Meta:
        model = Alumni
        fields = [
            'graduation_year', 'current_position', 'company', 'experience_level',
            'bio', 'linkedin_url', 'github_url', 'personal_website',
            'is_available_for_mentoring', 'is_show_in_alumni_list',
            'categories', 'technologies',
        ]

    def clean(self):
        cleaned = super().clean()
        for field_name in ('linkedin_url', 'github_url', 'personal_website'):
            value = cleaned.get(field_name)
            if value:
                try:
                    validate_public_website(value)
                except forms.ValidationError as exc:
                    self.add_error(field_name, exc)
        return cleaned


class WorkExperienceForm(forms.ModelForm):
    class Meta:
        model = WorkExperience
        fields = [
            'company', 'position', 'start_date', 'end_date',
            'is_current', 'description',
        ]

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        if cleaned.get('is_current'):
            cleaned['end_date'] = None
        elif start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'Bitiş tarihi başlangıç tarihinden önce olamaz.')
        return cleaned
