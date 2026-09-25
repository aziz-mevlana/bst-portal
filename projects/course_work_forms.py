from django import forms

from .course_work_models import CourseAssignmentCheckpoint, CourseProjectAssignment
from .models import Course, CourseInstructor


FIELD_CLASS = 'w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white focus:border-cyan-400 focus:outline-none'


class CourseProjectAssignmentForm(forms.ModelForm):
    class Meta:
        model = CourseProjectAssignment
        fields = ('course', 'topic', 'purpose', 'expectations', 'mode', 'min_team_size',
                  'max_team_size', 'join_deadline', 'starts_at', 'ends_at', 'repository_required')
        labels = {'course': 'Ders', 'topic': 'Proje Konusu', 'purpose': 'Projenin Amacı',
                  'expectations': 'Açıklama / Beklentiler', 'mode': 'Çalışma Tipi',
                  'min_team_size': 'Minimum Takım Büyüklüğü', 'max_team_size': 'Maksimum Takım Büyüklüğü',
                  'join_deadline': 'Katılım Son Tarihi', 'starts_at': 'Proje Başlangıç Tarihi',
                  'ends_at': 'Proje Bitiş Tarihi', 'repository_required': 'Proje Deposu Zorunlu'}
        widgets = {key: forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')
                   for key in ('join_deadline', 'starts_at', 'ends_at')}

    def __init__(self, *args, instructor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = Course.objects.filter(
            is_active=True, instructor_assignments__instructor=instructor,
            instructor_assignments__is_active=True
        ).exclude(code__in=['BST 401', 'BST 402']).distinct()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)


class CourseAssignmentCheckpointForm(forms.ModelForm):
    class Meta:
        model = CourseAssignmentCheckpoint
        fields = ('title', 'description', 'order', 'due_at', 'is_active')
        labels = {'title': 'Kontrol Noktası', 'description': 'Açıklama', 'order': 'Sıra',
                  'due_at': 'Son Tarih', 'is_active': 'Aktif'}
        widgets = {'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)


class CourseProjectWorkForm(forms.Form):
    title = forms.CharField(label='Proje Adı', max_length=200)
    idea = forms.CharField(label='Kısa Açıklama / Çözüm Fikri', widget=forms.Textarea)
    repository_path = forms.CharField(label='GitHub Deposu (kullanıcı/depo)', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)
