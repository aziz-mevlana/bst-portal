from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from PIL import Image
from django.db.models import Q

from core.form_utils import configure_required_choice
from .models import (
    CommunicationPreference, CommunityRegistration, DataSubjectRequest, PortfolioCertificate,
    Profile, UserReport,
)
from .validators import institutional_email_domain
from projects.models import ProjectCategory, Technology


INPUT_CLASS = 'w-full rounded-xl border border-gray-600 bg-[#181e29] p-3 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500'


class SettingsPasswordChangeForm(PasswordChangeForm):
    """Password form embedded below the fold without automatic page scrolling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs.pop('autofocus', None)


class ApprovedMemberApplicationForm(forms.ModelForm):
    class Meta:
        model = CommunityRegistration
        fields = ['introduction', 'motivation', 'content_plan', 'reference_url', 'additional_notes']
        labels = {
            'introduction': 'Kendinizi kısaca tanıtın',
            'motivation': 'Neden Onaylı Üye olmak istiyorsunuz?',
            'content_plan': 'Ne tür paylaşımlar yapmayı düşünüyorsunuz?',
            'reference_url': 'Varsa GitHub/LinkedIn/portfolyo bağlantısı',
            'additional_notes': 'Ek açıklama',
        }
        widgets = {
            'introduction': forms.Textarea(attrs={'rows': 4, 'placeholder': 'İlgi alanlarınız, deneyiminiz ve topluluklarla ilişkiniz'}),
            'motivation': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Onaylı Üye olmak istemenizin nedenini açıklayın'}),
            'content_plan': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Proje, teknik yazı, rehber, topluluk haberi vb.'}),
            'reference_url': forms.URLInput(attrs={'placeholder': 'https://github.com/... veya https://linkedin.com/in/...'}),
            'additional_notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Değerlendirmede bilinmesini istediğiniz diğer bilgiler'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['content_plan'].required = True


class PortfolioSettingsForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'headline', 'bio', 'graduation_year', 'class_level', 'github_username', 'linkedin_slug',
            'website_url', 'is_looking_for_job', 'is_looking_for_internship',
            'is_open_to_mentoring', 'is_open_to_team_offers', 'categories', 'technologies',
        ]
        widgets = {
            'headline': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: Backend geliştirici ve veri bilimi öğrencisi'}),
            'bio': forms.Textarea(attrs={'rows': 5, 'class': INPUT_CLASS, 'placeholder': 'Kendinizi, ilgi alanlarınızı, deneyiminizi ve hedeflerinizi anlatın'}),
            'graduation_year': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 2020, 'max': 2100, 'placeholder': 'Örn: 2027'}),
            'class_level': forms.Select(attrs={'class': INPUT_CLASS}),
            'github_username': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'oguzhanbodur'}),
            'linkedin_slug': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'oguzhan-bodur'}),
            'website_url': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'https://siteniz.com'}),
            'categories': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true', 'data-placeholder': 'İlgi alanı ara…'}),
            'technologies': forms.SelectMultiple(attrs={'data-enhance-multiselect': 'true', 'data-placeholder': 'Teknoloji ara…'}),
        }
        labels = {
            'headline': 'Kısa tanıtım', 'bio': 'Biyografi', 'graduation_year': 'Mezuniyet yılı',
            'class_level': 'Sınıf', 'github_username': 'GitHub kullanıcı adı',
            'linkedin_slug': 'LinkedIn profil kullanıcı adı',
            'website_url': 'Kişisel web sitesi', 'is_looking_for_job': 'İş arıyorum',
            'is_looking_for_internship': 'Staj arıyorum', 'is_open_to_mentoring': 'Mentorluğa açığım',
            'is_open_to_team_offers': 'Ekip tekliflerine açığım', 'categories': 'İlgi alanları',
            'technologies': 'Teknolojiler ve yetenekler',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        category_ids = self.instance.categories.values_list('pk', flat=True) if self.instance.pk else []
        technology_ids = self.instance.technologies.values_list('pk', flat=True) if self.instance.pk else []
        self.fields['categories'].queryset = ProjectCategory.objects.filter(Q(is_active=True) | Q(pk__in=category_ids)).distinct()
        self.fields['technologies'].queryset = Technology.objects.filter(Q(is_active=True) | Q(pk__in=technology_ids)).distinct()
        if self.instance.user_type not in {'student', 'staff_student'}:
            self.fields.pop('class_level', None)
        else:
            configure_required_choice(self.fields['class_level'], 'Sınıfınızı seçiniz')

    def clean_website_url(self):
        value = self.cleaned_data.get('website_url', '').strip()
        if value:
            from .validators import validate_public_website
            validate_public_website(value)
        return value

    def save(self, commit=True):
        old_url = ''
        if self.instance.pk:
            old_url = Profile.objects.filter(pk=self.instance.pk).values_list('website_url', flat=True).first() or ''
        profile = super().save(commit=False)
        new_url = self.cleaned_data.get('website_url', '')
        if old_url != new_url:
            profile.website_status = 'pending' if new_url else ''
            profile.website_reviewed_by = None
            profile.website_reviewed_at = None
            profile.website_rejection_reason = ''
            profile.website_moderation_description = ''
        if commit:
            profile.save()
            self.save_m2m()
            if old_url != new_url and new_url:
                from .models import WebsiteModerationHistory
                WebsiteModerationHistory.objects.create(
                    profile=profile, website_url=new_url, status='pending', description='Kullanıcı başvurusu.'
                )
        return profile


class PortfolioCertificateForm(forms.ModelForm):
    class Meta:
        model = PortfolioCertificate
        fields = ['title', 'issuer', 'issued_at', 'credential_url', 'credential_id', 'is_public']
        widgets = {
            'title': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Sertifika veya eğitim adı'}),
            'issuer': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Sertifikayı veren kurum'}),
            'issued_at': forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASS}),
            'credential_url': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'https://...'}),
            'credential_id': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Varsa sertifika numarası'}),
        }
        labels = {
            'title': 'Sertifika adı',
            'issuer': 'Veren kurum',
            'issued_at': 'Alınma tarihi',
            'credential_url': 'Doğrulama bağlantısı',
            'credential_id': 'Sertifika numarası',
            'is_public': 'Portfolyomda göster',
        }


class CommunicationPreferenceForm(forms.ModelForm):
    class Meta:
        model = CommunicationPreference
        fields = [
            'platform_notifications', 'email_announcements', 'email_project_updates',
            'email_application_results', 'email_events', 'email_mentorship', 'email_career',
        ]
        labels = {
            'platform_notifications': 'Platform bildirimleri',
            'email_announcements': 'Duyuru e-postaları',
            'email_project_updates': 'Proje güncellemeleri',
            'email_application_results': 'Başvuru sonuçları',
            'email_events': 'Etkinlikler',
            'email_mentorship': 'Mentorluk',
            'email_career': 'Kariyer ilanları',
        }


class DataSubjectRequestForm(forms.ModelForm):
    class Meta:
        model = DataSubjectRequest
        fields = ['request_type', 'explanation']
        widgets = {
            'request_type': forms.Select(attrs={'class': INPUT_CLASS}),
            'explanation': forms.Textarea(attrs={'rows': 4, 'class': INPUT_CLASS, 'placeholder': 'Talebinizin kapsamını ve hangi verilerle ilgili olduğunu açıklayın'}),
        }
        labels = {
            'request_type': 'Talep türü',
            'explanation': 'Açıklama',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_required_choice(self.fields['request_type'], 'KVKK talep türünü seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['request_type'].initial = ''


class AccountSettingsForm(forms.Form):
    first_name = forms.CharField(label='Ad', max_length=150, widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Adınız'}))
    last_name = forms.CharField(label='Soyad', max_length=150, widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Soyadınız'}))
    username = forms.CharField(label='Kullanıcı adı', max_length=150, widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Kullanıcı adınız'}))
    phone_number = forms.CharField(label='Telefon', max_length=30, required=False, widget=forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Örn: 0555 000 00 00'}))
    profile_picture = forms.ImageField(label='Profil fotoğrafı', required=False)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        initial = kwargs.setdefault('initial', {})
        initial.update({
            'first_name': user.first_name, 'last_name': user.last_name,
            'username': user.username, 'phone_number': user.profile.phone_number,
        })
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.exclude(pk=self.user.pk).filter(username__iexact=username).exists():
            raise forms.ValidationError('Bu kullanıcı adı kullanılıyor.')
        return username

    def clean_profile_picture(self):
        image = self.cleaned_data.get('profile_picture')
        if not image:
            return image
        if image.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Profil fotoğrafı en fazla 5 MB olabilir.')
        try:
            Image.open(image).verify()
            image.seek(0)
        except Exception as exc:
            raise forms.ValidationError('Geçerli bir görsel dosyası yükleyin.') from exc
        return image

    def save(self):
        self.user.first_name = self.cleaned_data['first_name'].strip()
        self.user.last_name = self.cleaned_data['last_name'].strip()
        self.user.username = self.cleaned_data['username']
        self.user.save(update_fields=['first_name', 'last_name', 'username'])
        profile = self.user.profile
        profile.phone_number = self.cleaned_data['phone_number'].strip()
        if self.cleaned_data.get('profile_picture'):
            profile.profile_picture = self.cleaned_data['profile_picture']
        profile.save()
        return self.user


class PrivacySettingsForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'is_portfolio_public', 'show_in_search', 'show_projects', 'show_contributions',
            'show_technologies', 'show_email', 'show_phone', 'show_class_level',
            'show_linkedin', 'show_github', 'show_personal_website', 'is_open_to_team_offers',
        ]
        labels = {
            'is_portfolio_public': 'Portfolyom herkese açık',
            'show_in_search': 'Arama sonuçlarında göster',
            'show_projects': 'Projelerimi göster',
            'show_contributions': 'Katkılarımı göster',
            'show_technologies': 'Teknolojilerimi göster',
            'show_email': 'E-posta adresimi göster',
            'show_phone': 'Telefon numaramı göster',
            'show_class_level': 'Sınıf bilgimi göster',
            'show_linkedin': 'LinkedIn bağlantımı göster',
            'show_github': 'GitHub bağlantımı göster',
            'show_personal_website': 'Onaylı kişisel sitemi göster',
            'is_open_to_team_offers': 'Ekip tekliflerine açığım',
        }


class EmailChangeForm(forms.Form):
    new_email = forms.EmailField(label='Yeni e-posta', widget=forms.EmailInput(attrs={'class': INPUT_CLASS, 'placeholder': 'ad.soyad@example.com'}))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_email(self):
        email = self.cleaned_data['new_email'].strip().lower()
        if self.user.profile.user_type not in {'alumni', 'visitor', 'approved_member'}:
            institutional_email_domain(email)
        if User.objects.exclude(pk=self.user.pk).filter(email__iexact=email).exists():
            raise forms.ValidationError('Bu e-posta adresi başka bir hesapta kullanılıyor.')
        if self.user.email.casefold() == email.casefold():
            raise forms.ValidationError('Yeni e-posta mevcut adresinizden farklı olmalıdır.')
        return email


class UserReportForm(forms.ModelForm):
    class Meta:
        model = UserReport
        fields = ['reason', 'description', 'related_content']
        labels = {
            'reason': 'Bildirim Nedeni',
            'description': 'Ayrıntılı Açıklama',
            'related_content': 'İlgili Sayfa Bağlantısı',
        }
        widgets = {
            'reason': forms.Select(attrs={'class': INPUT_CLASS}),
            'description': forms.Textarea(attrs={'class': INPUT_CLASS, 'rows': 5, 'placeholder': 'Durumu açık ve anlaşılır biçimde anlatın'}),
            'related_content': forms.URLInput(attrs={'class': INPUT_CLASS, 'placeholder': 'İlgili sayfa bağlantısı (isteğe bağlı)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_required_choice(self.fields['reason'], 'Bildirim nedenini seçiniz')
        if not self.is_bound and not self.instance.pk:
            self.fields['reason'].initial = ''
