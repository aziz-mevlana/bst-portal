from django import forms
from django.db.models import Q
from .models import Project, ProjectUpdate, ProjectComment, ProjectCategory, Technology, ProjectRequest, ProjectFeedback
from django.contrib.auth.models import User


class RequestForm(forms.ModelForm):
    class Meta:
        model = ProjectRequest
        fields = ['title', 'course', 'description', 'requirements', 'semester', 'deadline', 'team_size', 'status', 'supervision_type', 'categories', 'technologies']
        labels = {
            'title': 'Proje Başlığı',
            'course': 'Ders',
            'description': 'Açıklama',
            'requirements': 'Gerekli Koşullar',
            'semester': 'Dönem',
            'deadline': 'Son Başvuru Tarihi',
            'team_size': 'Ekip Büyüklüğü',
            'status': 'Durum',
            'supervision_type': 'Denetim Türü',
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all', 'placeholder': 'Proje başlığını giriniz'}),
            'course': forms.TextInput(attrs={'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all', 'placeholder': 'Örn: Yazılım Mühendisliği'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all resize-none', 'placeholder': 'Proje hakkında detaylı bilgi veriniz'}),
            'requirements': forms.Textarea(attrs={'rows': 3, 'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all resize-none', 'placeholder': 'Öğrencilerden beklenen ön koşullar'}),
            'semester': forms.Select(attrs={'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all'}),
            'deadline': forms.DateInput(attrs={'type': 'date', 'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all'}),
            'team_size': forms.NumberInput(attrs={'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all', 'placeholder': 'Örn: 3', 'min': '1', 'max': '10'}),
            'status': forms.Select(attrs={'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all'}),
            'supervision_type': forms.Select(attrs={'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['semester'].required = False
        self.fields['status'].required = False


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
        self.fields['team'].queryset = User.objects.filter(Q(profile__user_type='student')).distinct()
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


class ProjectFeedbackForm(forms.ModelForm):
    class Meta:
        model = ProjectFeedback
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Öğrenciye geri bildiriminizi yazın...', 'class': 'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 rounded-lg sm:rounded-xl text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all resize-none'}),
        }