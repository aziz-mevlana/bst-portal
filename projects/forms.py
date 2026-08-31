from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from django.urls import reverse
from pathlib import Path

from core.form_utils import configure_optional_choice, configure_required_choice
from accounts.validators import validate_public_website

from .models import (
    Project,
    ProjectAchievement,
    ProjectCaseStudy,
    ProjectCategory,
    ProjectComment,
    ProjectContribution,
    ProjectFeedback,
    ProjectMedia,
    detect_project_upload_type,
    validate_project_image,
    validate_project_upload_content,
    validate_project_upload_size,
    ProjectRequest,
    ProjectRequestApplication,
    ProjectRepository,
    Team,
    TeamMembership,
    TeamOpenRole,
    TeamRole,
    ProjectType,
    ProjectUpdate,
    Technology,
)


INPUT_CLASS = (
    'project-form-input w-full p-3 sm:p-4 bg-[#181e29] border border-gray-600 '
    'rounded-lg sm:rounded-xl text-white placeholder-gray-500 focus:ring-2 '
    'focus:ring-blue-500 focus:border-blue-500 focus:outline-none transition-all'
)


class RequestForm(forms.ModelForm):
    class Meta:
        model = ProjectRequest
        fields = [
            'title', 'project_type', 'course', 'description', 'requirements',
            'expected_output', 'estimated_duration', 'semester', 'year',
            'deadline', 'team_size', 'status', 'supervision_type', 'categories',
            'technologies',
        ]
        labels = {
            'title': 'Proje Başlığı',
            'project_type': 'Proje Türü',
            'course': 'Ders',
            'description': 'Açıklama',
            'requirements': 'Gerekli Yetenekler ve Koşullar',
            'expected_output': 'Beklenen Çıktı',
            'estimated_duration': 'Tahmini Süre',
            'semester': 'Dönem',
            'year': 'Yıl',
            'deadline': 'Son Başvuru Tarihi',
            'team_size': 'Ekip Büyüklüğü',
            'status': 'Durum',
            'supervision_type': 'Denetim Türü',
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Proje başlığını giriniz'}),
            'project_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'course': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: Yazılım Mühendisliği'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Projeyi ve çözmek istediğiniz problemi açıklayın'}),
            'requirements': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Öğrencide aranan bilgi ve yetenekler'}),
            'expected_output': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Proje sonunda beklenen çıktı'}),
            'estimated_duration': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: 12 hafta'}),
            'semester': forms.Select(attrs={'class': INPUT_CLASS}),
            'year': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 2020, 'max': 2100}),
            'deadline': forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASS}),
            'team_size': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 1, 'max': 10}),
            'status': forms.Select(attrs={'class': INPUT_CLASS}),
            'supervision_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'categories': forms.SelectMultiple(attrs={
                'data-enhance-multiselect': 'true',
                'data-placeholder': 'Kategori seçiniz',
            }),
            'technologies': forms.SelectMultiple(attrs={
                'data-enhance-multiselect': 'true',
                'data-placeholder': 'Teknoloji seçiniz',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_types = ProjectType.objects.filter(is_active=True)
        if self.instance and self.instance.pk:
            active_types = ProjectType.objects.filter(Q(is_active=True) | Q(pk=self.instance.project_type_id))
        self.fields['project_type'].queryset = active_types
        configure_required_choice(self.fields['project_type'], 'Proje türünü seçiniz')
        configure_optional_choice(self.fields['semester'], 'Dönem seçiniz (isteğe bağlı)')
        configure_required_choice(self.fields['status'], 'İlan durumunu seçiniz')
        configure_required_choice(self.fields['supervision_type'], 'Denetim türünü seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['project_type'].initial = ''
            self.fields['status'].initial = ''
            self.fields['supervision_type'].initial = ''
        category_ids = list(self.instance.categories.values_list('pk', flat=True)) if self.instance.pk else []
        technology_ids = list(self.instance.technologies.values_list('pk', flat=True)) if self.instance.pk else []
        self.fields['categories'].queryset = ProjectCategory.objects.filter(Q(is_active=True) | Q(pk__in=category_ids)).distinct()
        self.fields['technologies'].queryset = Technology.objects.filter(Q(is_active=True) | Q(pk__in=technology_ids)).distinct()

    def clean(self):
        cleaned = super().clean()
        project_type = cleaned.get('project_type')
        course = cleaned.get('course')
        if project_type and project_type.requires_course and not course:
            self.add_error('course', 'Bu proje türü için ders bilgisi zorunludur.')
        return cleaned


class ProjectRequestApplicationForm(forms.ModelForm):
    class Meta:
        model = ProjectRequestApplication
        fields = ['motivation', 'proposed_approach']
        labels = {
            'motivation': 'Motivasyonunuz',
            'proposed_approach': 'Önerdiğiniz Yaklaşım',
        }
        widgets = {
            'motivation': forms.Textarea(attrs={'rows': 5, 'class': INPUT_CLASS, 'placeholder': 'Bu projede neden yer almak istediğinizi anlatın'}),
            'proposed_approach': forms.Textarea(attrs={'rows': 5, 'class': INPUT_CLASS, 'placeholder': 'Projeye nasıl yaklaşacağınızı kısaca açıklayın'}),
        }


class ApplicationReviewForm(forms.Form):
    review_note = forms.CharField(
        required=False,
        label='Değerlendirme Notu',
        widget=forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Başvuruyla ilgili değerlendirmenizi yazın (isteğe bağlı)'}),
    )


class ProjectCaseStudyForm(forms.ModelForm):
    class Meta:
        model = ProjectCaseStudy
        fields = [
            'summary', 'problem', 'solution', 'architecture',
            'measurable_results', 'future_developments', 'demo_url',
        ]
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Projeyi birkaç cümlede özetleyin'}),
            'problem': forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Hangi gerçek problemi veya ihtiyacı ele aldığınızı açıklayın'}),
            'solution': forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Geliştirdiğiniz çözümü ve nasıl çalıştığını anlatın'}),
            'architecture': forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Teknik mimariyi, bileşenleri ve veri akışını açıklayın'}),
            'measurable_results': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Ölçülebilir sonuçları, testleri veya kazanımları yazın'}),
            'future_developments': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Bir sonraki sürümde geliştirmeyi planladığınız noktaları yazın'}),
            'demo_url': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'https://demo-adresi.com'}),
        }

    def clean_demo_url(self):
        value = self.cleaned_data.get('demo_url')
        validate_public_website(value)
        return value


class ProjectMediaForm(forms.ModelForm):
    class Meta:
        model = ProjectMedia
        fields = ['media_type', 'file', 'external_url', 'caption', 'alt_text', 'order', 'is_cover']
        labels = {
            'media_type': 'Medya Türü',
            'file': 'Dosya',
            'external_url': 'Harici Bağlantı',
            'caption': 'Kısa Açıklama',
            'alt_text': 'Alternatif Metin',
            'order': 'Gösterim Sırası',
            'is_cover': 'Kapak Olarak Kullan',
        }
        widgets = {
            'media_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'external_url': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'https://...'}),
            'caption': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Görsel veya videonun kısa açıklaması'}),
            'alt_text': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Erişilebilirlik için görselde ne olduğunu yazın'}),
            'order': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 0}),
            'is_cover': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['media_type'].choices = [
            choice for choice in ProjectMedia.MEDIA_TYPE_CHOICES
            if choice[0] in {'image', 'video', 'demo', 'document'}
        ]
        configure_required_choice(self.fields['media_type'], 'Medya türünü seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['media_type'].initial = ''

    def clean_external_url(self):
        value = self.cleaned_data.get('external_url')
        validate_public_website(value)
        return value


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)] if data else []


class ProjectImageUploadForm(forms.Form):
    cover_image = forms.ImageField(
        label='Kapak Görseli', required=False,
        widget=forms.ClearableFileInput(attrs={'accept': '.jpg,.jpeg,.png,.webp', 'class': INPUT_CLASS}),
    )
    project_logo = forms.ImageField(
        label='Proje Logosu', required=False,
        widget=forms.ClearableFileInput(attrs={'accept': '.jpg,.jpeg,.png,.webp', 'class': INPUT_CLASS}),
    )
    images = MultipleFileField(
        label='Proje Görselleri',
        required=False,
        widget=MultipleFileInput(attrs={'accept': '.jpg,.jpeg,.png,.webp', 'class': INPUT_CLASS}),
    )
    cover_index = forms.IntegerField(required=False, min_value=0, widget=forms.HiddenInput())
    pitch_deck = forms.FileField(
        label='Yatırımcı Sunumu (PDF)', required=False,
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,application/pdf', 'class': INPUT_CLASS}),
    )
    pitch_deck_is_public = forms.BooleanField(
        label='Yatırımcı sunumu herkese açık olsun', required=False, initial=False,
    )
    documentation = forms.FileField(
        label='Proje Dokümantasyonu (PDF)', required=False,
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,application/pdf', 'class': INPUT_CLASS}),
    )

    def clean_cover_image(self):
        image = self.cleaned_data.get('cover_image')
        if image:
            validate_project_image(image)
        return image

    def clean_project_logo(self):
        image = self.cleaned_data.get('project_logo')
        if image:
            validate_project_image(image)
        return image

    def _clean_pdf(self, field_name):
        upload = self.cleaned_data.get(field_name)
        if not upload:
            return upload
        validate_project_upload_size(upload)
        if Path(upload.name).suffix.casefold() != '.pdf' or detect_project_upload_type(upload) != 'document':
            raise forms.ValidationError('Yalnızca geçerli bir PDF dosyası yükleyebilirsiniz.')
        try:
            validate_project_upload_content(upload)
        except forms.ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return upload

    def clean_pitch_deck(self):
        return self._clean_pdf('pitch_deck')

    def clean_documentation(self):
        return self._clean_pdf('documentation')

    def clean_images(self):
        images = self.cleaned_data.get('images', [])
        if len(images) > 12:
            raise forms.ValidationError('Tek seferde en fazla 12 görsel yükleyebilirsiniz.')
        for image in images:
            validate_project_image(image)
        return images

    def clean(self):
        cleaned = super().clean()
        images = cleaned.get('images') or []
        cover_index = cleaned.get('cover_index')
        if cover_index is not None and cover_index >= len(images):
            self.add_error('cover_index', 'Kapak olarak seçilen görsel yükleme listesinde bulunamadı.')
        return cleaned


class ProjectContributionForm(forms.ModelForm):
    class Meta:
        model = ProjectContribution
        fields = ['user', 'role', 'contribution_description']
        labels = {
            'user': 'Katkı Sağlayan Kişi',
            'role': 'Projedeki Rolü',
            'contribution_description': 'Katkı Açıklaması',
        }
        widgets = {
            'user': forms.Select(attrs={'class': INPUT_CLASS}),
            'role': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: Arka uç geliştiricisi'}),
            'contribution_description': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Bu kişinin projeye yaptığı somut katkıyı açıklayın'}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            member_ids = set(project.team.values_list('pk', flat=True))
            member_ids.add(project.created_by_id)
            self.fields['user'].queryset = User.objects.filter(pk__in=member_ids, is_active=True)
        else:
            self.fields['user'].queryset = User.objects.none()
        configure_required_choice(self.fields['user'], 'Katkı sağlayan kişiyi seçiniz')


class ProjectAchievementForm(forms.ModelForm):
    class Meta:
        model = ProjectAchievement
        fields = [
            'title', 'organization', 'achievement_type', 'date', 'description',
            'certificate_url', 'evidence_file',
        ]
        labels = {
            'title': 'Başarı Başlığı',
            'organization': 'Veren Kurum',
            'achievement_type': 'Başarı Türü',
            'date': 'Tarih',
            'description': 'Açıklama',
            'certificate_url': 'Sertifika Bağlantısı',
            'evidence_file': 'Kanıt Dosyası',
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: Teknofest finalisti'}),
            'organization': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Ödülü veya başarıyı veren kurum'}),
            'achievement_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASS}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS, 'placeholder': 'Başarının kapsamını ve elde edilen sonucu açıklayın'}),
            'certificate_url': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'https://...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_required_choice(self.fields['achievement_type'], 'Başarı türünü seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['achievement_type'].initial = ''


class ProjectForm(forms.ModelForm):
    """Normal project form; academic-request projects can only be created by the service."""

    class Meta:
        model = Project
        fields = [
            'project_type', 'creation_source', 'title', 'description',
            'expected_output', 'project_link', 'advisor', 'team_entity', 'team', 'categories',
            'technologies', 'development_status', 'visibility',
        ]
        widgets = {
            'project_type': forms.Select(attrs={'class': 'project-form-input'}),
            'creation_source': forms.Select(attrs={'class': 'project-form-input'}),
            'title': forms.TextInput(attrs={'class': 'project-form-input', 'placeholder': 'Örn: Akıllı kampüs yönlendirme sistemi'}),
            'description': forms.Textarea(attrs={'rows': 5, 'class': 'project-form-input', 'placeholder': 'Projenin çözdüğü problemi, hedefini ve temel çalışma biçimini açıklayın'}),
            'expected_output': forms.Textarea(attrs={'rows': 3, 'class': 'project-form-input', 'placeholder': 'Örn: Çalışan web uygulaması, mobil uygulama veya araştırma raporu'}),
            'project_link': forms.URLInput(attrs={'class': 'project-form-input', 'placeholder': 'https://projeniz.com veya canlı demo bağlantısı'}),
            'advisor': forms.Select(attrs={'class': 'project-form-input'}),
            'team_entity': forms.Select(attrs={'class': 'project-form-input'}),
            'team': forms.SelectMultiple(attrs={
                'data-enhance-multiselect': 'true',
                'data-async-users': 'true',
                'data-placeholder': 'Takım üyesi ara ve ekle',
            }),
            'categories': forms.SelectMultiple(attrs={
                'data-enhance-multiselect': 'true',
                'data-placeholder': 'Kategori seçiniz',
            }),
            'technologies': forms.SelectMultiple(attrs={
                'data-enhance-multiselect': 'true',
                'data-placeholder': 'Teknoloji seçiniz',
            }),
            'development_status': forms.Select(attrs={'class': 'project-form-input'}),
            'visibility': forms.Select(attrs={'class': 'project-form-input'}),
        }

        labels = {
            'project_type': 'Proje türü',
            'creation_source': 'Projenin kaynağı',
            'title': 'Proje başlığı',
            'description': 'Proje açıklaması',
            'expected_output': 'Beklenen çıktı',
            'project_link': 'Proje bağlantısı',
            'advisor': 'Akademik danışman',
            'team_entity': 'Bağlı ekip',
            'team': 'Takım üyeleri',
            'categories': 'Kategoriler',
            'technologies': 'Teknolojiler',
            'development_status': 'Geliştirme durumu',
            'visibility': 'Görünürlük',
        }

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user
        self.fields['team'].widget.attrs['data-async-url'] = reverse('projects:team_member_search')
        team_queryset = User.objects.filter(profile__user_type='student', is_active=True).select_related('profile').distinct()
        if current_user and current_user.is_authenticated:
            team_queryset = team_queryset.exclude(pk=current_user.pk)
        self.fields['team'].queryset = team_queryset
        self.fields['advisor'].queryset = User.objects.filter(profile__user_type='teacher', is_active=True).distinct()
        configure_optional_choice(self.fields['advisor'], 'Danışman seçiniz (isteğe bağlı)')
        team_entities = Team.objects.none()
        if current_user and current_user.is_authenticated:
            team_entities = Team.objects.filter(leader=current_user)
        if self.instance and self.instance.pk and self.instance.team_entity_id:
            team_entities = Team.objects.filter(Q(leader=current_user) | Q(pk=self.instance.team_entity_id)).distinct()
        self.fields['team_entity'].queryset = team_entities
        configure_optional_choice(self.fields['team_entity'], 'Ekip seçiniz (isteğe bağlı)')
        category_ids = list(self.instance.categories.values_list('pk', flat=True)) if self.instance.pk else []
        technology_ids = list(self.instance.technologies.values_list('pk', flat=True)) if self.instance.pk else []
        self.fields['categories'].queryset = ProjectCategory.objects.filter(Q(is_active=True) | Q(pk__in=category_ids)).distinct()
        self.fields['technologies'].queryset = Technology.objects.filter(Q(is_active=True) | Q(pk__in=technology_ids)).distinct()
        project_types = ProjectType.objects.filter(is_active=True)
        if self.instance and self.instance.pk:
            project_types = ProjectType.objects.filter(Q(is_active=True) | Q(pk=self.instance.project_type_id))
        self.fields['project_type'].queryset = project_types
        configure_required_choice(self.fields['project_type'], 'Proje türünü seçiniz')
        self.fields['creation_source'].choices = [
            choice for choice in Project.CREATION_SOURCE_CHOICES
            if choice[0] not in {'ACADEMIC_REQUEST', 'LEGACY'}
        ]
        configure_required_choice(self.fields['creation_source'], 'Projenin kaynağını seçiniz')
        configure_required_choice(self.fields['development_status'], 'Geliştirme durumunu seçiniz')
        configure_required_choice(self.fields['visibility'], 'Görünürlüğü seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['project_type'].initial = ''
            self.fields['creation_source'].initial = ''
            self.fields['development_status'].initial = ''
            self.fields['visibility'].initial = ''
        if self.instance and self.instance.pk and self.instance.creation_source == 'ACADEMIC_REQUEST':
            self.fields['creation_source'].choices = [('ACADEMIC_REQUEST', 'Akademisyen İlanı')]
            self.fields['creation_source'].disabled = True
            self.fields['project_type'].disabled = True

    def clean_team(self):
        team = self.cleaned_data['team']
        if self.current_user and team.filter(pk=self.current_user.pk).exists():
            raise forms.ValidationError('Proje sahibi takım listesine yeniden eklenemez.')
        return team

    def clean_project_link(self):
        value = self.cleaned_data.get('project_link')
        validate_public_website(value)
        return value

    def clean_creation_source(self):
        source = self.cleaned_data['creation_source']
        if source in {'ACADEMIC_REQUEST', 'LEGACY'}:
            if not self.instance.pk or source != self.instance.creation_source:
                raise forms.ValidationError('Bu proje kaynağı normal proje formundan seçilemez.')
        return source


class ProjectUpdateForm(forms.ModelForm):
    class Meta:
        model = ProjectUpdate
        fields = ['version', 'title', 'description']
        labels = {'version': 'Sürüm', 'title': 'Güncelleme Başlığı', 'description': 'Güncelleme Açıklaması'}
        widgets = {
            'version': forms.TextInput(attrs={'class': 'project-form-input', 'placeholder': 'Örn: v0.3 (isteğe bağlı)'}),
            'title': forms.TextInput(attrs={'class': 'project-form-input', 'placeholder': 'Güncelleme başlığı...'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'project-form-input', 'placeholder': 'Güncelleme detaylarını buraya yazın...'}),
        }


class ProjectCommentForm(forms.ModelForm):
    content = forms.CharField(
        label='Yorumunuz',
        min_length=2,
        max_length=2000,
        strip=True,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'maxlength': 2000,
            'placeholder': 'Projeyle ilgili görüşünüzü, sorunuzu veya yapıcı geri bildiriminizi yazın…',
            'class': 'project-form-input',
        }),
    )

    class Meta:
        model = ProjectComment
        fields = ['content']


class ProjectRepositoryForm(forms.ModelForm):
    class Meta:
        model = ProjectRepository
        fields = ['repository_path']
        labels = {'repository_path': 'GitHub deposu'}
        widgets = {
            'repository_path': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'kullanici/depo',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['repository_path'].required = False
        self.fields['repository_path'].help_text = 'Yalnızca kullanıcı/depo biçimini girin. Tam GitHub bağlantısı girmeyin.'

    def clean_repository_path(self):
        value = self.cleaned_data.get('repository_path', '').strip()
        if not value:
            return ''
        owner, name = ProjectRepository.parse_repository_path(value)
        return f'{owner}/{name}'


class TeamForm(forms.ModelForm):
    leader_role = forms.ChoiceField(
        choices=[('', 'Rol seçiniz'), *TeamRole.choices],
        required=False,
        initial=TeamRole.TEAM_LEAD,
        label='Ekipteki Rolünüz',
        help_text='Bu seçim profilinizde görünen ekip içi rolünüzdür.',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )

    class Meta:
        model = Team
        fields = ['name', 'description', 'leader_role', 'technologies', 'work_areas', 'recruitment_open']
        labels = {
            'name': 'Ekip Adı',
            'description': 'Açıklama',
            'technologies': 'Teknolojiler',
            'work_areas': 'Çalışma Alanları',
            'recruitment_open': 'Üye Alımı Açık',
        }
        help_texts = {
            'name': 'Ekip listesinde görünecek kısa ve ayırt edici ad.',
            'description': 'Ekibin hedefini, çalışma biçimini ve üretmek istediği projeleri açıklayın.',
            'technologies': 'Ekibin kullandığı veya öğrenmek istediği teknolojileri seçin.',
            'work_areas': 'Ekibin odaklandığı çalışma alanlarını seçin.',
            'recruitment_open': 'Yeni üyelerden davet ve iletişim almaya açıksanız işaretleyin.',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: BST Vision'}),
            'description': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 5, 'placeholder': 'Ekibin çalışma alanını ve hedeflerini anlatın'}),
            'technologies': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true', 'data-search-placeholder': 'Teknoloji ara…'}),
            'work_areas': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true', 'data-search-placeholder': 'Çalışma alanı ara…'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = True

    def clean_description(self):
        description = self.cleaned_data.get('description', '').strip()
        if len(description) < 20:
            raise forms.ValidationError('Ekip açıklaması en az 20 karakter olmalıdır.')
        return description


class TeamInviteForm(forms.Form):
    invited_user = forms.ModelChoiceField(queryset=User.objects.none(), label='Davet edilecek kullanıcı')
    proposed_role = forms.ChoiceField(
        choices=[('', 'Rol seçiniz'), *TeamRole.choices],
        required=True,
        label='Ekip içi rol',
        widget=forms.Select(attrs={'class': INPUT_CLASS}),
    )

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        member_ids = team.members.values_list('pk', flat=True) if team else []
        self.fields['invited_user'].queryset = User.objects.filter(
            is_active=True, profile__user_type__in=['student', 'staff_student', 'alumni']
        ).exclude(pk__in=member_ids).select_related('profile')
        self.fields['invited_user'].widget.attrs['class'] = INPUT_CLASS
        self.fields['invited_user'].empty_label = 'Kullanıcı seçiniz'
        self.fields['invited_user'].help_text = 'Yalnızca aktif öğrenci, BST Yetkilisi ve mezun hesapları listelenir.'
        self.fields['proposed_role'].help_text = 'Davet kabul edildiğinde üyeye bu rol atanır.'


class TeamMembershipRoleForm(forms.ModelForm):
    class Meta:
        model = TeamMembership
        fields = ['role']
        labels = {'role': 'Ekip içi rol'}
        widgets = {'role': forms.Select(attrs={'class': INPUT_CLASS})}


class TeamOpenRoleForm(forms.ModelForm):
    class Meta:
        model = TeamOpenRole
        fields = ['title', 'description', 'required_technologies', 'is_open']
        labels = {
            'title': 'Açık Rol Başlığı',
            'description': 'Açıklama',
            'required_technologies': 'Gerekli Teknolojiler',
            'is_open': 'Başvurulara Açık',
        }
        help_texts = {
            'title': 'Ekipte ihtiyaç duyduğunuz rolü listeden seçin.',
            'description': 'Beklentileri ve ekip üyesinin üstleneceği görevleri açıklayın.',
            'required_technologies': 'Rol için gerekli veya tercih edilen teknolojileri seçin.',
        }
        widgets = {
            'title': forms.Select(attrs={'class': INPUT_CLASS}),
            'description': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 3, 'placeholder': 'Rolün sorumluluklarını açıklayın'}),
            'required_technologies': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true'}),
        }


class ProjectFeedbackForm(forms.ModelForm):
    class Meta:
        model = ProjectFeedback
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Öğrenciye geri bildiriminizi yazın...', 'class': INPUT_CLASS}),
        }
