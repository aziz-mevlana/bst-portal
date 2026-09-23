from django import forms

from .academic_models import CapstoneMeetingRequest, CapstonePlanCheckpoint


class PlanCheckpointForm(forms.ModelForm):
    class Meta:
        model = CapstonePlanCheckpoint
        fields = ('title', 'description', 'order', 'due_at')
        labels = {'title': 'Kontrol Noktası Adı', 'description': 'Açıklama', 'order': 'Sıra',
                  'due_at': 'Son Teslim Tarihi'}
        widgets = {'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}


class AcademicSubmissionForm(forms.Form):
    note = forms.CharField(label='Teslim notu', required=False, widget=forms.Textarea(attrs={'rows': 3}))
    links = forms.CharField(label='Bağlantılar (her satıra bir bağlantı)', required=False,
                            widget=forms.Textarea(attrs={'rows': 2}))


class AcademicReviewForm(forms.Form):
    decision = forms.ChoiceField(label='Karar', choices=[('APPROVED', 'Onayla'),
                                                         ('REVISION_REQUIRED', 'Revizyon İste')])
    feedback = forms.CharField(label='Geri Bildirim', required=False,
                               widget=forms.Textarea(attrs={'rows': 3}))


class LiteratureForm(forms.Form):
    file = forms.FileField(label='Literatür Raporu (PDF)')
    note = forms.CharField(label='Sürüm notu', required=False, widget=forms.Textarea(attrs={'rows': 2}))
    checkpoint = forms.ModelChoiceField(queryset=CapstonePlanCheckpoint.objects.none(), required=False,
                                        label='İlgili Kontrol Noktası')

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            self.fields['checkpoint'].queryset = CapstonePlanCheckpoint.objects.filter(
                plan__term=project.term, plan__advisor_id=project.project.advisor_id, is_active=True)


class HelpRequestForm(forms.Form):
    subject = forms.CharField(label='Konu', max_length=200)
    description = forms.CharField(label='Açıklama', widget=forms.Textarea(attrs={'rows': 4}))
    file = forms.FileField(label='Dosya', required=False)
    checkpoint = forms.ModelChoiceField(queryset=CapstonePlanCheckpoint.objects.none(), required=False,
                                        label='İlgili Kontrol Noktası')

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            self.fields['checkpoint'].queryset = CapstonePlanCheckpoint.objects.filter(
                plan__term=project.term, plan__advisor_id=project.project.advisor_id, is_active=True)


class MeetingRequestForm(forms.Form):
    subject = forms.CharField(label='Konu', max_length=200)
    description = forms.CharField(label='Açıklama', widget=forms.Textarea(attrs={'rows': 3}))
    availability_note = forms.CharField(label='Uygun olduğunuz zamanlar', widget=forms.Textarea(attrs={'rows': 2}))
    checkpoint = forms.ModelChoiceField(queryset=CapstonePlanCheckpoint.objects.none(), required=False,
                                        label='İlgili Kontrol Noktası')

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            self.fields['checkpoint'].queryset = CapstonePlanCheckpoint.objects.filter(
                plan__term=project.term, plan__advisor_id=project.project.advisor_id, is_active=True)


class MeetingDecisionForm(forms.Form):
    scheduled_at = forms.DateTimeField(label='Görüşme tarihi ve saati', required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        input_formats=['%Y-%m-%dT%H:%M'])
    note = forms.CharField(label='Ret gerekçesi', required=False, widget=forms.Textarea(attrs={'rows': 2}))


class ExtensionForm(forms.Form):
    due_at = forms.DateTimeField(label='Öğrenciye özel son tarih',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        input_formats=['%Y-%m-%dT%H:%M'])
    reason = forms.CharField(label='Gerekçe', widget=forms.Textarea(attrs={'rows': 2}))


class TextForm(forms.Form):
    content = forms.CharField(label='Metin', widget=forms.Textarea(attrs={'rows': 3}), max_length=5000)
