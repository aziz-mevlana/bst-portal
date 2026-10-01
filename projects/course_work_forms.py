from django import forms

from .course_work_models import CourseAssignmentCheckpoint, CourseProjectAssignment, CourseProjectTemplate
from .models import Course
from .course_requirements import KINDS, MODES, default_requirements, validate_requirements


FIELD_CLASS = 'w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white focus:border-cyan-400 focus:outline-none'


class CourseProjectAssignmentForm(forms.ModelForm):
    class Meta:
        model = CourseProjectAssignment
        fields = ('course', 'topic', 'purpose', 'expectations', 'mode', 'min_team_size',
                  'max_team_size', 'join_deadline', 'starts_at', 'ends_at', 'repository_required')
        labels = {'course': 'Ders', 'topic': 'Proje Konusu', 'purpose': 'Projenin Amacı',
                  'expectations': 'Açıklama / Beklentiler', 'mode': 'Çalışma Tipi',
                  'min_team_size': 'Minimum Ekip Büyüklüğü', 'max_team_size': 'Maksimum Ekip Büyüklüğü',
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
        if self.instance.pk:
            self.fields['course'].queryset = Course.objects.filter(pk=self.instance.course_id)
            self.fields['course'].disabled = True
            if self.instance.participants.exists():
                self.fields['mode'].disabled = True
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border border-slate-600 accent-cyan-600' if isinstance(field.widget, forms.CheckboxInput) else FIELD_CLASS)


class CourseProjectWorkForm(forms.Form):
    title = forms.CharField(label='Proje Adı', max_length=200)
    idea = forms.CharField(label='Kısa Açıklama / Çözüm Fikri', widget=forms.Textarea)
    repository_path = forms.CharField(label='GitHub Deposu (kullanıcı/depo)', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border border-slate-600 accent-cyan-600' if isinstance(field.widget, forms.CheckboxInput) else FIELD_CLASS)


class RequirementFieldsMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = getattr(self.instance, 'evidence_requirements', None) if hasattr(self, 'instance') else None
        config = config or self.initial.get('evidence_requirements') or default_requirements()
        for kind, (label, limit) in KINDS.items():
            prefix = kind.lower()
            self.fields[f'{prefix}_mode'] = forms.ChoiceField(label=f'{label} — kullanım', choices=MODES, initial=config[kind]['mode'])
            self.fields[f'{prefix}_min'] = forms.IntegerField(label=f'{label} — minimum', min_value=0, max_value=limit, initial=config[kind]['min_count'])
            self.fields[f'{prefix}_max'] = forms.IntegerField(label=f'{label} — azami (boş: sistem sınırı)', min_value=0, max_value=limit, required=False, initial=config[kind]['max_count'])
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border border-slate-600 accent-cyan-600' if isinstance(field.widget, forms.CheckboxInput) else FIELD_CLASS)

    @property
    def definition_fields(self):
        requirement_names = {f'{kind.lower()}_{suffix}' for kind in KINDS for suffix in ('mode','min','max')}
        return [self[name] for name in self.fields if name not in requirement_names]

    @property
    def requirement_groups(self):
        return [{'label': label, 'mode': self[f'{kind.lower()}_mode'],
                 'minimum': self[f'{kind.lower()}_min'], 'maximum': self[f'{kind.lower()}_max']}
                for kind,(label,limit) in KINDS.items()]

    def clean(self):
        data = super().clean()
        config = {}
        for kind in KINDS:
            p = kind.lower()
            if all(f'{p}_{x}' in data for x in ('mode', 'min', 'max')):
                config[kind] = dict(mode=data.pop(f'{p}_mode'), min_count=data.pop(f'{p}_min'), max_count=data.pop(f'{p}_max'))
        if len(config) == len(KINDS):
            validate_requirements(config)
            data['evidence_requirements'] = config
        return data


class CourseAssignmentCheckpointForm(RequirementFieldsMixin, forms.ModelForm):
    class Meta:
        model = CourseAssignmentCheckpoint
        fields = ('title', 'description', 'order', 'due_at', 'is_active', 'scoring_enabled', 'max_points')
        labels = {'title': 'Kontrol Noktası', 'description': 'Açıklama', 'order': 'Sıra',
                  'due_at': 'Son Tarih', 'is_active': 'Aktif',
                  'scoring_enabled': 'Puanlama kullan (akademisyene özel)', 'max_points': 'Azami Puan'}
        widgets = {'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border border-slate-600 accent-cyan-600' if isinstance(field.widget, forms.CheckboxInput) else FIELD_CLASS)


    def _post_clean(self):
        if 'evidence_requirements' in self.cleaned_data:
            self.instance.evidence_requirements = self.cleaned_data['evidence_requirements']
        super()._post_clean()


class CoursePlanCheckpointForm(RequirementFieldsMixin, forms.Form):
    title = forms.CharField(label='Kontrol noktası', max_length=200)
    description = forms.CharField(label='Açıklama', required=False, max_length=10000, widget=forms.Textarea(attrs={'rows': 2}))
    order = forms.IntegerField(label='Sıra', min_value=1, max_value=32767)
    due_at = forms.DateTimeField(label='Yeni son tarih', required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    scoring_enabled = forms.BooleanField(label='Puanlama kullan (akademisyene özel)', required=False)
    max_points = forms.IntegerField(label='Azami puan', min_value=1, max_value=32767, initial=10)
    expected_items = forms.CharField(label='Beklenenler (her satıra bir madde)', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, include_dates=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not include_dates:
            self.fields.pop('due_at')
        else:
            self.fields['due_at'].required = True

    def clean_expected_items(self):
        items = [line.strip() for line in self.cleaned_data['expected_items'].splitlines() if line.strip()]
        if len(items) > 100 or any(len(item)>300 for item in items):
            raise forms.ValidationError('En fazla 100 madde, her biri en fazla 300 karakter.')
        return items


CoursePlanFormSet = forms.formset_factory(CoursePlanCheckpointForm, extra=0, can_delete=True, max_num=100, validate_max=True, absolute_max=100)


class CourseProjectTemplateForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput, initial=0, min_value=0)
    class Meta:
        model = CourseProjectTemplate
        fields = ('name', 'topic', 'purpose', 'expectations', 'mode', 'min_team_size', 'max_team_size', 'repository_required', 'is_archived')
        labels = {'name': 'Şablon adı', **CourseProjectAssignmentForm.Meta.labels, 'is_archived': 'Arşivle'}
        widgets = {key: forms.Textarea(attrs={'rows': 3}) for key in ('purpose', 'expectations')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['version'] = self.instance.version
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border border-slate-600 accent-cyan-600' if isinstance(field.widget, forms.CheckboxInput) else FIELD_CLASS)


class CourseEvidenceForm(forms.Form):
    completion_note = forms.CharField(label='Metin açıklaması', max_length=20000, required=False, widget=forms.Textarea(attrs={'rows': 3}))
    evidence_links = forms.CharField(label='Linkler (her satıra bir URL)', max_length=10000, required=False, widget=forms.Textarea(attrs={'rows': 3}))
    references = forms.CharField(label='Kaynakça (her satıra başlık | isteğe bağlı URL)', max_length=100000, required=False, widget=forms.Textarea(attrs={'rows': 4}))

    def __init__(self, *args, checkpoint, **kwargs):
        super().__init__(*args, **kwargs)
        self.requirements = checkpoint.evidence_requirements
        for kind, name in [('TEXT', 'completion_note'), ('LINK', 'evidence_links'), ('REFERENCE', 'references')]:
            rule = self.requirements[kind]
            if rule['mode'] == 'DISABLED':
                self.fields.pop(name)
            else:
                self.fields[name].required = rule['mode'] == 'REQUIRED'
                maximum = rule['max_count'] if rule['max_count'] is not None else KINDS[kind][1]
                self.fields[name].help_text = f'{dict(MODES)[rule["mode"]]} · minimum {rule["min_count"]} · azami {maximum}'
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border border-slate-600 accent-cyan-600' if isinstance(field.widget, forms.CheckboxInput) else FIELD_CLASS)

    @staticmethod
    def parse_references(raw):
        result = []
        for line in raw.splitlines():
            if line.strip():
                title, separator, url = line.partition('|')
                result.append({'title': title.strip(), 'url': url.strip() if separator else ''})
        return result

    def clean_references(self):
        return self.parse_references(self.cleaned_data.get('references', ''))


class CourseReviewForm(forms.Form):
    outcome = forms.ChoiceField(label='Karar', choices=[('APPROVED','Onaylandı'),('REVISION_REQUIRED','Revizyon gerekli')])
    feedback = forms.CharField(label='Öğrenciye geri bildirim', required=False, widget=forms.Textarea(attrs={'rows': 3}))
    private_note = forms.CharField(label='Akademisyen Özel Notu', max_length=10000, required=False, widget=forms.Textarea(attrs={'rows': 3}))
    private_score = forms.IntegerField(label='Gizli Akademisyen Değerlendirmesi', min_value=0, required=False)

    def __init__(self, *args, checkpoint, private_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        if private_only:
            self.fields.pop('outcome'); self.fields.pop('feedback')
        if checkpoint.scoring_enabled:
            self.fields['private_score'].max_value = checkpoint.max_points
            from django.core.validators import MaxValueValidator
            self.fields['private_score'].validators.append(MaxValueValidator(checkpoint.max_points))
            self.fields['private_score'].help_text = f'Azami: {checkpoint.max_points} · öğrenciye gösterilmez'
        else:
            self.fields.pop('private_score')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border border-slate-600 accent-cyan-600' if isinstance(field.widget, forms.CheckboxInput) else FIELD_CLASS)

    def clean(self):
        data = super().clean()
        if data.get('outcome') == 'REVISION_REQUIRED' and not data.get('feedback','').strip():
            self.add_error('feedback', 'Revizyon için geri bildirim zorunludur.')
        return data
