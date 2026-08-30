from django import forms
from django.db.models import Q
from django.utils import timezone

from core.form_utils import configure_optional_choice, configure_required_choice
from projects.forms import INPUT_CLASS

from .models import CollaborationRequest, MentorshipProfile, MentorshipRequest, MentorshipReview, Opportunity


class OpportunityForm(forms.ModelForm):
    class Meta:
        model = Opportunity
        fields = [
            'title', 'opportunity_type', 'organization', 'description', 'requirements',
            'technologies', 'location', 'work_mode', 'application_url',
            'contact_method', 'contact_email', 'deadline',
        ]
        labels = {
            'title': 'İlan Başlığı',
            'opportunity_type': 'İlan Türü',
            'organization': 'Şirket / Kurum',
            'description': 'İlan Açıklaması',
            'requirements': 'Aranan Nitelikler',
            'technologies': 'İlgili Teknolojiler',
            'location': 'Konum',
            'work_mode': 'Çalışma Şekli',
            'application_url': 'Başvuru Bağlantısı',
            'contact_method': 'Başvuru Yöntemi',
            'contact_email': 'Başvuru E-postası',
            'deadline': 'Son Başvuru Tarihi',
        }
        help_texts = {
            'description': 'Pozisyonun kapsamını, sorumlulukları ve adayın kazanımlarını açıklayın.',
            'requirements': 'Zorunlu ve tercih edilen şartları anlaşılır maddeler halinde yazın.',
            'technologies': 'İlanla doğrudan ilişkili teknolojileri seçin.',
            'application_url': 'Başvuru yöntemi bağlantı ise doldurulması zorunludur.',
            'contact_email': 'Başvuru yöntemi e-posta ise doldurulması zorunludur.',
            'deadline': 'Boş bırakırsanız ilan sürekli açık olarak görünür.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: Django geliştirici stajyeri'}),
            'opportunity_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'organization': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Kurum veya şirket adı'}),
            'description': forms.Textarea(attrs={'rows': 6, 'class': INPUT_CLASS, 'placeholder': 'Pozisyonu, sorumlulukları ve adayın neler yapacağını açıklayın'}),
            'requirements': forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Aranan yetkinlikleri ve başvuru koşullarını yazın'}),
            'technologies': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true', 'data-search-placeholder': 'Teknoloji ara…'}),
            'location': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: İstanbul veya uzaktan'}),
            'work_mode': forms.Select(attrs={'class': INPUT_CLASS}),
            'application_url': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'https://...'}),
            'contact_method': forms.Select(attrs={'class': INPUT_CLASS}),
            'contact_email': forms.EmailInput(attrs={'class': INPUT_CLASS, 'placeholder': 'basvuru@kurum.com'}),
            'deadline': forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_required_choice(self.fields['opportunity_type'], 'İlan türünü seçiniz')
        configure_required_choice(self.fields['work_mode'], 'Çalışma şeklini seçiniz')
        configure_required_choice(self.fields['contact_method'], 'Başvuru yöntemini seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['opportunity_type'].initial = ''
            self.fields['work_mode'].initial = ''
            self.fields['contact_method'].initial = ''
        selected = self.instance.technologies.values_list('pk', flat=True) if self.instance.pk else []
        self.fields['technologies'].queryset = self.fields['technologies'].queryset.filter(
            Q(is_active=True) | Q(pk__in=selected)
        ).distinct()

    def clean_deadline(self):
        deadline = self.cleaned_data.get('deadline')
        if deadline and deadline < timezone.localdate():
            raise forms.ValidationError('Son başvuru tarihi geçmiş bir gün olamaz.')
        return deadline

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('contact_method')
        if method == 'url':
            cleaned['contact_email'] = ''
        elif method == 'email':
            cleaned['application_url'] = ''
        elif method == 'portal':
            cleaned['application_url'] = ''
            cleaned['contact_email'] = ''
        return cleaned


class MentorshipProfileForm(forms.ModelForm):
    class Meta:
        model = MentorshipProfile
        fields = ['is_available', 'mentoring_topics', 'monthly_capacity', 'preferred_contact_method', 'availability_note']
        labels = {
            'is_available': 'Mentorluk Taleplerine Açığım',
            'mentoring_topics': 'Mentorluk Konuları',
            'monthly_capacity': 'Aylık Görüşme Kapasitesi',
            'preferred_contact_method': 'Tercih Edilen İletişim Yöntemi',
            'availability_note': 'Uygunluk Notu',
        }
        widgets = {
            'mentoring_topics': forms.SelectMultiple(attrs={'data-enhance-multiselect': '', 'data-search-placeholder': 'Konu ara…'}),
            'monthly_capacity': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 1, 'max': 20}),
            'preferred_contact_method': forms.Select(attrs={'class': INPUT_CLASS}),
            'availability_note': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_required_choice(self.fields['preferred_contact_method'], 'İletişim yöntemini seçiniz')
        selected = self.instance.mentoring_topics.values_list('pk', flat=True) if self.instance.pk else []
        self.fields['mentoring_topics'].queryset = self.fields['mentoring_topics'].queryset.filter(
            Q(is_active=True) | Q(pk__in=selected)
        ).distinct()


class MentorshipRequestForm(forms.ModelForm):
    class Meta:
        model = MentorshipRequest
        fields = ['topic', 'goal', 'message']
        labels = {'topic': 'Mentorluk Konusu', 'goal': 'Görüşme Hedefiniz', 'message': 'Mentora Mesajınız'}
        widgets = {
            'topic': forms.Select(attrs={'class': INPUT_CLASS}),
            'goal': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Bu mentorluk görüşmesinden hedefinizi kısaca yazın'}),
            'message': forms.Textarea(attrs={'rows': 5, 'class': INPUT_CLASS, 'placeholder': 'Kendinizi, ihtiyacınızı ve sormak istediklerinizi anlatın'}),
        }

    def __init__(self, *args, mentor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if mentor:
            self.fields['topic'].queryset = mentor.mentoring_topics.all()
        configure_optional_choice(self.fields['topic'], 'Konu seçiniz (isteğe bağlı)')


class MentorshipResponseForm(forms.Form):
    mentor_response = forms.CharField(label='Mentor Yanıtı', required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Öğrenciye iletmek istediğiniz yanıtı yazın'}))


class MentorshipReviewForm(forms.ModelForm):
    class Meta:
        model = MentorshipReview
        fields = ['rating', 'comment']
        labels = {'rating': 'Puan', 'comment': 'Değerlendirmeniz'}
        widgets = {
            'rating': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 1, 'max': 5}),
            'comment': forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Mentorluk deneyiminizi kısaca değerlendirin'}),
        }


class CollaborationRequestForm(forms.ModelForm):
    website_check = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = CollaborationRequest
        fields = [
            'contact_name', 'organization', 'job_title', 'email', 'phone', 'website',
            'request_type', 'interest_reference', 'title', 'description',
            'preferred_contact', 'consent_accepted',
        ]
        widgets = {
            'contact_name': forms.TextInput(attrs={'class': INPUT_CLASS, 'autocomplete': 'name', 'placeholder': 'Adınız ve soyadınız'}),
            'organization': forms.TextInput(attrs={'class': INPUT_CLASS, 'autocomplete': 'organization', 'placeholder': 'Şirket veya kurum adı'}),
            'job_title': forms.TextInput(attrs={'class': INPUT_CLASS, 'autocomplete': 'organization-title', 'placeholder': 'Örn: İnsan Kaynakları Uzmanı'}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASS, 'autocomplete': 'email', 'placeholder': 'ornek@kurum.com'}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASS, 'autocomplete': 'tel', 'placeholder': 'Örn: 0555 000 00 00'}),
            'website': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'https://'}),
            'request_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'interest_reference': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Varsa proje veya öğrenci/ekip adı'}),
            'title': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Talebinizi tek cümleyle özetleyen başlık'}),
            'description': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 7, 'placeholder': 'İhtiyacınızı, kapsamı, hedefi ve varsa zaman planını ayrıntılı açıklayın'}),
            'preferred_contact': forms.Select(attrs={'class': INPUT_CLASS}),
            'consent_accepted': forms.CheckboxInput(attrs={'class': 'h-5 w-5 rounded border-gray-600 bg-gray-900'}),
        }
        error_messages = {
            'email': {'invalid': 'Geçerli bir e-posta adresi girin.'},
            'website': {'invalid': 'Web sitesi adresini https:// ile birlikte girin.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_required_choice(self.fields['request_type'], 'Talep türünü seçiniz')
        configure_required_choice(self.fields['preferred_contact'], 'İletişim yöntemini seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['request_type'].initial = ''
            self.fields['preferred_contact'].initial = ''

    def clean_website_check(self):
        value = self.cleaned_data.get('website_check', '')
        if value:
            raise forms.ValidationError('Form doğrulanamadı.')
        return value

    def clean_consent_accepted(self):
        value = self.cleaned_data.get('consent_accepted')
        if not value:
            raise forms.ValidationError('Talebi göndermek için KVKK ve iletişim onayı zorunludur.')
        return value


class CollaborationReviewForm(forms.ModelForm):
    class Meta:
        model = CollaborationRequest
        fields = [
            'normalized_title', 'normalized_description', 'publication_channel',
            'assigned_teacher', 'project_type', 'expected_output', 'deadline',
            'categories', 'technologies', 'admin_note',
        ]
        labels = {
            'normalized_title': 'Yayın Başlığı',
            'normalized_description': 'Yayın Açıklaması',
            'publication_channel': 'Yayın Kanalı',
            'assigned_teacher': 'Sorumlu Akademisyen',
            'project_type': 'Proje Türü',
            'expected_output': 'Beklenen Çıktı',
            'deadline': 'Son Başvuru Tarihi',
            'categories': 'Kategoriler',
            'technologies': 'Teknolojiler',
            'admin_note': 'Yönetici Notu',
        }
        widgets = {
            'normalized_title': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Yayımlanacak kısa ve anlaşılır başlık'}),
            'normalized_description': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 6, 'placeholder': 'Yayımlanacak talep açıklaması'}),
            'publication_channel': forms.Select(attrs={'class': INPUT_CLASS}),
            'assigned_teacher': forms.Select(attrs={'class': INPUT_CLASS}),
            'project_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'expected_output': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 4, 'placeholder': 'Talep sonunda beklenen somut çıktıyı yazın'}),
            'deadline': forms.DateInput(attrs={'class': INPUT_CLASS, 'type': 'date'}),
            'categories': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true', 'data-search-placeholder': 'Kategori ara…'}),
            'technologies': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true', 'data-search-placeholder': 'Teknoloji ara…'}),
            'admin_note': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 4, 'placeholder': 'Yalnızca yöneticilerin göreceği inceleme notu'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_required_choice(self.fields['publication_channel'], 'Yayın kanalını seçiniz')
        configure_optional_choice(self.fields['assigned_teacher'], 'Akademisyen seçiniz (gerekiyorsa)')
        configure_optional_choice(self.fields['project_type'], 'Proje türünü seçiniz (gerekiyorsa)')
        self.fields['assigned_teacher'].queryset = self.fields['assigned_teacher'].queryset.filter(
            is_active=True, profile__user_type='teacher'
        )
        self.fields['project_type'].queryset = self.fields['project_type'].queryset.filter(is_active=True)
        selected_categories = self.instance.categories.values_list('pk', flat=True) if self.instance.pk else []
        selected_technologies = self.instance.technologies.values_list('pk', flat=True) if self.instance.pk else []
        self.fields['categories'].queryset = self.fields['categories'].queryset.filter(
            Q(is_active=True) | Q(pk__in=selected_categories)
        ).distinct()
        self.fields['technologies'].queryset = self.fields['technologies'].queryset.filter(
            Q(is_active=True) | Q(pk__in=selected_technologies)
        ).distinct()
