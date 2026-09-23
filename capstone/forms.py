from django import forms
from django.contrib.auth import get_user_model

from .models import CapstoneCheckpointEvaluation, CapstoneSubmissionReview, CapstoneTask


User = get_user_model()


class CapstoneStartForm(forms.Form):
    title = forms.CharField(
        label='Proje başlığı',
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full',
            'placeholder': 'Bitirme projenizin başlığı',
        }),
    )
    description = forms.CharField(
        label='Proje açıklaması',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-textarea w-full',
            'rows': 6,
            'placeholder': 'Projenizin amacını ve kapsamını kısaca açıklayın',
        }),
    )
    advisor = forms.ModelChoiceField(
        label='Danışman',
        queryset=User.objects.none(),
        empty_label='Danışman seçin',
        widget=forms.Select(attrs={'class': 'form-select w-full'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['advisor'].queryset = (
            User.objects.filter(
                is_active=True,
                is_staff=False,
                is_superuser=False,
                profile__user_type='teacher',
            )
            .select_related('profile')
            .order_by('first_name', 'last_name', 'username')
        )


class CapstoneTaskForm(forms.ModelForm):
    class Meta:
        model = CapstoneTask
        fields = ('title', 'instructions', 'required_file_count', 'due_at')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input w-full'}),
            'instructions': forms.Textarea(attrs={
                'class': 'form-textarea w-full',
                'rows': 4,
            }),
            'required_file_count': forms.NumberInput(attrs={
                'class': 'form-input w-full',
                'min': 1,
                'max': 20,
            }),
            'due_at': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'class': 'form-input w-full', 'type': 'datetime-local'},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].label = 'Görev başlığı'
        self.fields['instructions'].label = 'Görev açıklaması'
        self.fields['required_file_count'].label = 'Gerekli dosya sayısı'
        self.fields['required_file_count'].widget.attrs['min'] = 1
        self.fields['required_file_count'].widget.attrs['max'] = 20
        self.fields['due_at'].label = 'Son teslim tarihi'
        self.fields['due_at'].input_formats = ['%Y-%m-%dT%H:%M']


class CapstoneReviewForm(forms.Form):
    decision = forms.ChoiceField(
        label='Karar',
        choices=CapstoneSubmissionReview.Decision.choices,
        widget=forms.Select(attrs={'class': 'form-select w-full'}),
    )
    feedback = forms.CharField(
        label='Geri bildirim',
        max_length=5000,
        strip=True,
        widget=forms.Textarea(attrs={
            'class': 'form-textarea w-full',
            'rows': 4,
            'placeholder': 'Öğrenciye akademik geri bildiriminizi yazın',
        }),
    )


class CapstoneProposalRejectForm(forms.Form):
    advisor_note = forms.CharField(label='Ret gerekçesi', max_length=5000, strip=True,
                                   widget=forms.Textarea(attrs={'class': 'form-textarea w-full', 'rows': 3}))


class CapstoneEvaluationForm(forms.ModelForm):
    class Meta:
        model = CapstoneCheckpointEvaluation
        fields = ('score', 'feedback')
        labels = {'score': 'Puan', 'feedback': 'Akademik geri bildirim'}
        widgets = {
            'score': forms.NumberInput(attrs={'class': 'form-input w-full', 'min': 0}),
            'feedback': forms.Textarea(attrs={'class': 'form-textarea w-full', 'rows': 3}),
        }
