from django import forms
from django.db.models import Q
from .models import Project, ProjectUpdate, ProjectComment, ProjectCategory, Technology, ProjectRequest
from django.contrib.auth.models import User


class RequestForm(forms.ModelForm):
    class Meta:
        model = ProjectRequest
        fields = ['title', 'course', 'duration', 'team_size']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input'}),
            'course': forms.TextInput(attrs={'class': 'project-form-input'}),
            'duration': forms.TextInput(attrs={'class': 'project-form-input'}),
            'team_size': forms.NumberInput(attrs={'class': 'project-form-input'}),
        }


class ProjectForm(forms.ModelForm):
    """Form used by views but mapped to new Project model."""
    class Meta:
        model = Project
        fields = ['project_request', 'title', 'description', 'project_link', 'team', 'categories', 'technologies', 'is_private']
        widgets = {
            'project_request': forms.Select(attrs={'class': 'project-form-input'}),
            'title': forms.TextInput(attrs={'class': 'project-form-input'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input'}),
            'project_link': forms.TextInput(attrs={'class': 'project-form-input'}),
            'team': forms.SelectMultiple(attrs={'class': 'project-form-input'}),
            'categories': forms.CheckboxSelectMultiple(attrs={'class': 'space-y-2'}),
            'technologies': forms.CheckboxSelectMultiple(attrs={'class': 'space-y-2'}),
            'is_private': forms.CheckboxInput(attrs={'class': 'w-5 h-5 accent-blue-500 cursor-pointer'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['team'].queryset = User.objects.filter(Q(profile__user_type='student') | Q(old_profile__user_type='student')).distinct()
        # Rename field for better user experience
        self.fields['project_request'].label = 'Project Request'


class ProjectUpdateForm(forms.ModelForm):
    class Meta:
        model = ProjectUpdate
        fields = ['title', 'note']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input', 'placeholder': 'Güncelleme başlığı...'}),
            'note': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input', 'placeholder': 'Güncelleme detaylarını buraya yazın...'}),
        }


class ProjectCommentForm(forms.ModelForm):
    class Meta:
        model = ProjectComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Yorumunuzu yazın...', 'class': 'project-form-input'}),
        }