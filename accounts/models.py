import secrets
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse
from django.contrib.auth.hashers import check_password, make_password
from django.utils.crypto import constant_time_compare
from datetime import timedelta
from projects.models import ProjectCategory, Technology
from .validators import validate_github_username, validate_linkedin_slug, validate_public_website


MODERATION_REASON_CHOICES = [
    ('inappropriate_content', 'Uygunsuz içerik'),
    ('spam', 'Spam'),
    ('harassment', 'Taciz / kötü davranış'),
    ('misleading', 'Sahte / yanıltıcı bilgi'),
    ('community_violation', 'Topluluk kuralları ihlali'),
    ('security_concern', 'Güvenlik şüphesi'),
    ('inappropriate_profile', 'Uygunsuz profil içeriği'),
    ('other', 'Diğer'),
]


class EmailVerification(models.Model):
    email = models.EmailField()
    code = models.CharField(max_length=6, blank=True)
    code_hash = models.CharField(max_length=128, blank=True)
    session_data = models.JSONField(default=dict)
    password_hash = models.CharField(max_length=128, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Email Verification"
        verbose_name_plural = "Email Verifications"

    def __str__(self):
        return f"{self.email} - {self.code}"

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @staticmethod
    def generate_code():
        return str(secrets.randbelow(900000) + 100000)

    def set_code(self, raw_code):
        self.code = ''
        self.code_hash = make_password(raw_code)

    def matches_code(self, raw_code):
        if self.code_hash:
            return check_password(raw_code, self.code_hash)
        return constant_time_compare(raw_code, self.code)


class PasswordReset(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6, blank=True)
    code_hash = models.CharField(max_length=128, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Password Reset"
        verbose_name_plural = "Password Resets"

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @staticmethod
    def generate_code():
        return str(secrets.randbelow(900000) + 100000)

    def set_code(self, raw_code):
        self.code = ''
        self.code_hash = make_password(raw_code)

    def matches_code(self, raw_code):
        if self.code_hash:
            return check_password(raw_code, self.code_hash)
        return constant_time_compare(raw_code, self.code)


class Profile(models.Model):
    """User profile information"""
    USER_TYPE_CHOICES = [
        ('student', 'Öğrenci'),
        ('teacher', 'Akademisyen'),
        ('alumni', 'Mezun'),
        ('staff_student', 'BST Yetkilisi'),
        ('visitor', 'Ziyaretçi'),
        ('approved_member', 'Onaylı Üye'),
    ]
    ACCOUNT_STATUS_CHOICES = [
        ('pending_email', 'E-posta doğrulaması bekleniyor'),
        ('pending_review', 'İnceleme bekleniyor'),
        ('active', 'Aktif'),
        ('suspended', 'Geçici olarak askıya alındı'),
        ('closed', 'Kalıcı olarak kapatıldı'),
    ]

    TEACHER_TITLE_CHOICES = [
        ('', 'Ünvan Seçin'),
        ('prof_dr', 'Prof. Dr.'),
        ('doc_dr', 'Doç. Dr.'),
        ('dr_ogr_uyesi', 'Dr. Öğr. Üyesi'),
        ('dr', 'Dr.'        ),
        ('arastirma_gorevlisi', 'Araştırma Görevlisi'),
        ('ogretim_gorevlisi', 'Öğretim Görevlisi'),
        ('okutman', 'Okutman'),
        ('uzman', 'Uzman'),
    ]
    
    CLASS_CHOICES = [
        ('1', '1. Sınıf'),
        ('2', '2. Sınıf'),
        ('3', '3. Sınıf'),
        ('4', '4. Sınıf'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    public_slug = models.SlugField(max_length=170, unique=True, blank=True)
    user_type = models.CharField(max_length=15, choices=USER_TYPE_CHOICES, default='student')
    teacher_title = models.CharField(max_length=30, choices=TEACHER_TITLE_CHOICES, blank=True, null=True)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    first_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30, blank=True, null=True)
    student_number = models.CharField(max_length=20, blank=True, null=True)
    class_level = models.CharField(max_length=1, choices=CLASS_CHOICES, blank=True, null=True, default='1')
    department = models.CharField(max_length=100, blank=True, null=True, default='Bilişim Sistemleri ve Teknolojileri')
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)
    headline = models.CharField(max_length=160, blank=True)
    bio = models.TextField(blank=True)
    graduation_year = models.PositiveSmallIntegerField(blank=True, null=True)
    github_username = models.CharField(max_length=39, blank=True, validators=[validate_github_username])
    linkedin_slug = models.CharField(max_length=100, blank=True, validators=[validate_linkedin_slug])
    website_url = models.URLField(blank=True, validators=[validate_public_website])
    website_status = models.CharField(
        max_length=12,
        choices=[('pending', 'İnceleme bekliyor'), ('approved', 'Onaylandı'), ('rejected', 'Reddedildi')],
        blank=True,
    )
    website_reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_profile_websites'
    )
    website_reviewed_at = models.DateTimeField(blank=True, null=True)
    website_rejection_reason = models.CharField(max_length=32, choices=MODERATION_REASON_CHOICES, blank=True)
    website_moderation_description = models.TextField(blank=True)
    is_looking_for_job = models.BooleanField(default=False)
    is_looking_for_internship = models.BooleanField(default=False)
    is_open_to_mentoring = models.BooleanField(default=False)
    is_open_to_team_offers = models.BooleanField(default=True)
    is_portfolio_public = models.BooleanField(default=True)
    show_email = models.BooleanField(default=False)
    show_phone = models.BooleanField(default=False)
    show_class_level = models.BooleanField(default=True)
    show_projects = models.BooleanField(default=True)
    show_contributions = models.BooleanField(default=True)
    show_technologies = models.BooleanField(default=True)
    show_in_search = models.BooleanField(default=True)
    show_linkedin = models.BooleanField(default=True)
    show_github = models.BooleanField(default=True)
    show_personal_website = models.BooleanField(default=True)
    institutional_email_verified_at = models.DateTimeField(blank=True, null=True)
    student_number_verified = models.BooleanField(default=False)
    account_status = models.CharField(max_length=20, choices=ACCOUNT_STATUS_CHOICES, default='active', db_index=True)
    must_change_password = models.BooleanField(default=False, verbose_name='İlk girişte şifre değişikliği gerekli')
    suspension_reason = models.TextField(blank=True)
    suspended_until = models.DateTimeField(blank=True, null=True)
    academic_approved_at = models.DateTimeField(blank=True, null=True)
    academic_approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_academics')
    is_featured = models.BooleanField(default=False)
    featured_from = models.DateTimeField(blank=True, null=True)
    featured_until = models.DateTimeField(blank=True, null=True)
    featured_order = models.PositiveSmallIntegerField(default=0)
    
    # Skills and Technologies
    categories = models.ManyToManyField(ProjectCategory, related_name='student_profiles', blank=True)
    technologies = models.ManyToManyField(Technology, related_name='student_profiles', blank=True)
    showcase_projects = models.ManyToManyField(
        'projects.Project',
        related_name='showcased_by_profiles',
        blank=True,
        verbose_name='Profilde sergilenen projeler',
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"
        constraints = [
            models.UniqueConstraint(
                fields=['student_number'],
                condition=models.Q(student_number__isnull=False) & ~models.Q(student_number=''),
                name='unique_nonempty_student_number',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        user_type__in=['student', 'staff_student'],
                        class_level__isnull=False,
                        class_level__in=['1', '2', '3', '4'],
                    )
                    | (
                        models.Q(user_type__in=['teacher', 'alumni', 'visitor', 'approved_member'])
                        & models.Q(class_level__isnull=True)
                    )
                ),
                name='class_level_matches_student_role',
            ),
        ]
        permissions = [
            ('moderate_accounts', 'Can perform limited account moderation'),
            ('end_user_sessions', 'Can terminate active user sessions'),
            ('review_profile_websites', 'Can review personal website submissions'),
            ('review_user_reports', 'Can review user reports'),
            ('review_alumni_registrations', 'Can review alumni registration requests'),
            ('review_project_requests', 'Can review project requests'),
            ('review_collaborations', 'Can perform first review of collaboration requests'),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_user_type_display()}"

    def get_absolute_url(self):
        if self.user_type == 'teacher' and not self.user.is_staff and not self.user.is_superuser:
            return reverse('portal:academic_detail', kwargs={'slug': self.public_slug})
        if (
            self.user_type in {'student', 'staff_student'}
            and not self.user.is_staff
            and not self.user.is_superuser
        ):
            return reverse('portal:portfolio_detail', kwargs={'slug': self.public_slug})
        return reverse('accounts:profile')

    def save(self, *args, **kwargs):
        if self.user_type not in {'student', 'staff_student'}:
            self.class_level = None
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'class_level'}
        if not self.public_slug:
            base = slugify(self.user.get_full_name() or self.user.username) or f'user-{self.user_id}'
            candidate = base
            counter = 2
            while type(self).objects.filter(public_slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{counter}'
                counter += 1
            self.public_slug = candidate
        super().save(*args, **kwargs)

    def get_display_title(self):
        if self.user_type == 'teacher' and self.teacher_title:
            return self.get_teacher_title_display()
        return ''

    @property
    def github_url(self):
        return f'https://github.com/{self.github_username}' if self.github_username else ''

    @property
    def linkedin_url(self):
        return f'https://www.linkedin.com/in/{self.linkedin_slug}' if self.linkedin_slug else ''

    @property
    def approved_website_url(self):
        return self.website_url if self.website_status == 'approved' else ''

    @property
    def personal_website(self):
        """Backwards-compatible public accessor; pending/rejected links never leak."""
        return self.approved_website_url

    @property
    def is_currently_featured(self):
        now = timezone.now()
        return bool(
            self.is_featured
            and (self.featured_from is None or self.featured_from <= now)
            and (self.featured_until is None or self.featured_until >= now)
        )


class CommunityRegistration(models.Model):
    STATUS_CHOICES = [
        ('visitor', 'Ziyaretçi olarak kayıtlı'),
        ('pending', 'Onaylı Üye incelemesi bekleniyor'),
        ('approved', 'Onaylı Üye olarak onaylandı'),
        ('rejected', 'Onaylı Üye başvurusu reddedildi'),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='community_registration',
        verbose_name='Kullanıcı',
    )
    introduction = models.TextField('Kısa Tanıtım', max_length=1000)
    motivation = models.TextField('Onaylı Üye Olma Nedeni', max_length=1500)
    wants_to_share = models.BooleanField('Onaylı Üye Başvurusu Yapıldı', default=False)
    content_plan = models.TextField('Planlanan Paylaşım Türleri', max_length=2000, blank=True)
    reference_url = models.URLField('GitHub / LinkedIn / Portfolyo Bağlantısı', max_length=500, blank=True)
    additional_notes = models.TextField('Ek Açıklama', max_length=1500, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='visitor', db_index=True)
    reviewer_note = models.TextField('İnceleme Notu', max_length=1000, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_contributor_applications', verbose_name='İnceleyen',
    )
    reviewed_at = models.DateTimeField('İnceleme Tarihi', null=True, blank=True)
    created_at = models.DateTimeField('Başvuru Tarihi', auto_now_add=True)
    updated_at = models.DateTimeField('Güncellenme Tarihi', auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Onaylı Üye başvurusu'
        verbose_name_plural = 'Onaylı Üye başvuruları'
        permissions = [
            ('review_contributor_applications', 'Can review approved member applications'),
        ]

    def clean(self):
        super().clean()
        if self.wants_to_share and not self.content_plan.strip():
            raise ValidationError({'content_plan': 'Onaylı Üye başvurusu için paylaşmayı düşündüğünüz içerikleri açıklayın.'})
        if self.wants_to_share and self.status == 'visitor':
            raise ValidationError({'status': 'İçerik paylaşmak isteyen kayıtlar incelemeye alınmalıdır.'})
        if not self.wants_to_share and self.status != 'visitor':
            raise ValidationError({'status': 'İçerik paylaşımı istemeyen kayıt yalnızca ziyaretçi olabilir.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} · {self.get_status_display()}'


class PortfolioCertificate(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='certificates')
    title = models.CharField(max_length=200)
    issuer = models.CharField(max_length=180)
    issued_at = models.DateField(blank=True, null=True)
    credential_url = models.URLField(blank=True)
    credential_id = models.CharField(max_length=120, blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issued_at', '-created_at']

    def __str__(self):
        return f'{self.title} - {self.profile.user.get_full_name() or self.profile.user.username}'


class ConsentRecord(models.Model):
    CONSENT_TYPE_CHOICES = [
        ('terms', 'Kullanım Koşulları'),
        ('privacy_notice', 'KVKK Aydınlatma Metni'),
        ('marketing_email', 'Tanıtım ve Duyuru E-postaları'),
    ]

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='consent_records')
    consent_type = models.CharField(max_length=30, choices=CONSENT_TYPE_CHOICES)
    text_version = models.CharField(max_length=30)
    accepted = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'consent_type', '-created_at'], name='consent_user_type_date_idx')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Rıza kayıtları değiştirilemez.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Rıza kayıtları silinemez.')


class CommunicationPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='communication_preferences')
    email_announcements = models.BooleanField(default=False)
    email_project_updates = models.BooleanField(default=True)
    email_events = models.BooleanField(default=False)
    platform_notifications = models.BooleanField(default=True)
    email_application_results = models.BooleanField(default=True)
    email_mentorship = models.BooleanField(default=True)
    email_career = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class DataSubjectRequest(models.Model):
    REQUEST_TYPE_CHOICES = [
        ('export', 'Verilerimi Dışa Aktar'),
        ('anonymize', 'Hesabımı Anonimleştir'),
        ('delete', 'Hesabımı Sil'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Bekliyor'),
        ('reviewing', 'İnceleniyor'),
        ('completed', 'Tamamlandı'),
        ('rejected', 'Reddedildi'),
    ]

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='data_subject_requests')
    request_type = models.CharField(max_length=12, choices=REQUEST_TYPE_CHOICES)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    explanation = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'request_type'],
                condition=models.Q(status__in=['pending', 'reviewing']),
                name='one_open_data_request_per_type',
            ),
        ]


class UserModerationAction(models.Model):
    ACTION_CHOICES = [
        ('suspend', 'Geçici askıya alma'), ('reactivate', 'Yeniden etkinleştirme'),
        ('close', 'Kalıcı kapatma'), ('request_reverification', 'Yeniden e-posta doğrulaması isteme'),
        ('remove_photo', 'Profil fotoğrafını kaldırma'), ('end_sessions', 'Aktif oturumları sonlandırma'),
        ('approve_academic', 'Akademisyen onayı'), ('reject_academic', 'Akademisyen reddi'),
    ]
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='moderation_actions')
    action_type = models.CharField(max_length=32, choices=ACTION_CHOICES)
    reason = models.CharField(max_length=32, choices=MODERATION_REASON_CHOICES)
    description = models.TextField(default='')
    performed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='performed_moderation_actions')
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class WebsiteModerationHistory(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name='website_moderation_history')
    website_url = models.URLField(validators=[validate_public_website])
    status = models.CharField(
        max_length=12,
        choices=[('pending', 'İnceleme bekliyor'), ('approved', 'Onaylandı'), ('rejected', 'Reddedildi')],
    )
    reason = models.CharField(max_length=32, choices=MODERATION_REASON_CHOICES, blank=True)
    description = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name='profile_website_actions'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Web sitesi moderasyon geçmişi değiştirilemez.')
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Web sitesi moderasyon geçmişi silinemez.')


class UserReport(models.Model):
    REASON_CHOICES = [
        ('impersonation', 'Sahte veya taklit hesap'), ('harassment', 'Taciz veya uygunsuz davranış'),
        ('spam', 'Spam'), ('inappropriate', 'Uygunsuz içerik'), ('other', 'Diğer'),
    ]
    STATUS_CHOICES = [('open', 'Açık'), ('reviewing', 'İnceleniyor'), ('resolved', 'Çözüldü'), ('dismissed', 'İşlem yapılmadı')]
    reporter = models.ForeignKey(User, on_delete=models.PROTECT, related_name='submitted_user_reports')
    reported_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='received_user_reports')
    related_content = models.CharField(max_length=500, blank=True)
    reason = models.CharField(max_length=24, choices=REASON_CHOICES)
    description = models.TextField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='open')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_user_reports')
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=~models.Q(reporter=models.F('reported_user')), name='reporter_cannot_report_self')]

# Signal handlers
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created and not hasattr(instance, '_creating_profile'):
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()


@receiver(post_save, sender=Profile)
def sync_bst_authority_membership(sender, instance, **kwargs):
    from .roles import sync_user_authority_group
    sync_user_authority_group(instance.user, instance.user_type)
