from django import forms
from .models import Respons, ResponsUpdate, Comment
from django.contrib.auth.models import User


class RequestForm(forms.ModelForm):
    class Meta:
        model = __import__('projects.models', fromlist=['Request']).Request
        fields = ['title', 'course', 'duration', 'team_size']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input'}),
            'course': forms.TextInput(attrs={'class': 'project-form-input'}),
            'duration': forms.TextInput(attrs={'class': 'project-form-input'}),
            'team_size': forms.NumberInput(attrs={'class': 'project-form-input'}),
        }


class ProjectForm(forms.ModelForm):
    """Form used by views but mapped to the new Respons model."""
    class Meta:
        model = Respons
        fields = ['title', 'description', 'advisor', 'project_link', 'status', 'team']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input'}),
            'advisor': forms.Select(attrs={'class': 'project-form-input'}),
            'project_link': forms.TextInput(attrs={'class': 'project-form-input'}),
            'status': forms.TextInput(attrs={'class': 'project-form-input'}),
            'team': forms.SelectMultiple(attrs={'class': 'project-form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # advisor and team queryset filters assume UserProfile exists
        self.fields['advisor'].queryset = User.objects.filter(profile__user_type='teacher')
        self.fields['team'].queryset = User.objects.filter(profile__user_type='student')


class ProjectUpdateForm(forms.ModelForm):
    class Meta:
        model = ResponsUpdate
        fields = ['which_respons', 'when', 'project_status', 'notify_teacher', 'note']
        widgets = {
            'note': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input'}),
        }


class ProjectCommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Yorumunuzu yazın...', 'class': 'project-form-input'}),
        }