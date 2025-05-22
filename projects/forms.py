from django import forms
from .models import Project, ProjectUpdate, ProjectComment
from django.contrib.auth.models import User

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            'title', 'description', 'supervisor', 'project_url',
            'status', 'category', 'start_date', 'deadline',
            'is_public', 'team_members', 'attachments'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input'}),
            'supervisor': forms.Select(attrs={'class': 'project-form-input'}),
            'project_url': forms.TextInput(attrs={'class': 'project-form-input'}),
            'status': forms.Select(attrs={'class': 'project-form-input'}),
            'category': forms.Select(attrs={'class': 'project-form-input'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'project-form-input'}),
            'deadline': forms.DateInput(attrs={'type': 'date', 'class': 'project-form-input'}),
            'is_public': forms.CheckboxInput(attrs={'class': 'project-form-input'}),
            'team_members': forms.SelectMultiple(attrs={'class': 'project-form-input'}),
            'attachments': forms.FileInput(attrs={'class': 'project-form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supervisor'].queryset = User.objects.filter(profile__user_type='teacher')
        self.fields['team_members'].queryset = User.objects.filter(profile__user_type='student')

class ProjectUpdateForm(forms.ModelForm):
    class Meta:
        model = ProjectUpdate
        fields = ['title', 'content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input'}),
        }

class ProjectCommentForm(forms.ModelForm):
    class Meta:
        model = ProjectComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Yorumunuzu yazın...', 'class': 'project-form-input'}),
        } 