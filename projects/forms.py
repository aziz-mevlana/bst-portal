from django import forms
from .models import Respons, ResponsUpdate, Comment, ProjectCategory, Technology, Request
from django.contrib.auth.models import User


class RequestForm(forms.ModelForm):
    class Meta:
        model = Request
        fields = ['title', 'course', 'duration', 'team_size']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input'}),
            'course': forms.TextInput(attrs={'class': 'project-form-input'}),
            'duration': forms.TextInput(attrs={'class': 'project-form-input'}),
            'team_size': forms.NumberInput(attrs={'class': 'project-form-input'}),
        }


class ProjectForm(forms.ModelForm):
    """Form used by views but mapped to new Respons model."""
    class Meta:
        model = Respons
        fields = ['request', 'advisor', 'title', 'description', 'project_link', 'team', 'categories', 'technologies']
        widgets = {
            'request': forms.Select(attrs={'class': 'project-form-input'}),
            'advisor': forms.Select(attrs={'class': 'project-form-input'}),
            'title': forms.TextInput(attrs={'class': 'project-form-input'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input'}),
            'project_link': forms.TextInput(attrs={'class': 'project-form-input'}),
            'team': forms.SelectMultiple(attrs={'class': 'project-form-input'}),
            'categories': forms.CheckboxSelectMultiple(attrs={'class': 'space-y-2'}),
            'technologies': forms.CheckboxSelectMultiple(attrs={'class': 'space-y-2'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['advisor'].queryset = User.objects.filter(profile__user_type='teacher')
        self.fields['team'].queryset = User.objects.filter(profile__user_type='student')


class ProjectUpdateForm(forms.ModelForm):
    class Meta:
        model = ResponsUpdate
        fields = ['title', 'note']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input', 'placeholder': 'Güncelleme başlığı...'}),
            'note': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input', 'placeholder': 'Güncelleme detaylarını buraya yazın...'}),
        }


class ProjectCommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Yorumunuzu yazın...', 'class': 'project-form-input'}),
        }