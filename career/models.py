from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from alumni.models import Alumni
from projects.models import ProjectCategory, Technology


class Opportunity(models.Model):
    TYPE_CHOICES = [
        ('internship', 'Staj'),
        ('part_time', 'Part-time'),
        ('full_time', 'Full-time'),
        ('volunteer', 'Gönüllü proje'),
        ('freelance', 'Freelance'),
        ('teammate', 'Yarışma ekip arkadaşı'),
    ]
    WORK_MODE_CHOICES = [('onsite', 'Ofiste'), ('hybrid', 'Hibrit'), ('remote', 'Uzaktan')]
    CONTACT_CHOICES = [('url', 'Başvuru bağlantısı'), ('email', 'E-posta'), ('portal', 'Portal profili')]
    APPROVAL_CHOICES = [('pending', 'Onay bekliyor'), ('approved', 'Onaylandı'), ('rejected', 'Reddedildi')]

    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=210, unique=True, blank=True)
    opportunity_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    organization = models.CharField(max_length=180)
    description = models.TextField()
    requirements = models.TextField(blank=True)
    technologies = models.ManyToManyField(Technology, related_name='opportunities', blank=True)
    location = models.CharField(max_length=180, blank=True)
    work_mode = models.CharField(max_length=12, choices=WORK_MODE_CHOICES)
    application_url = models.URLField(blank=True)
    contact_method = models.CharField(max_length=12, choices=CONTACT_CHOICES, default='url')
    contact_email = models.EmailField(blank=True)
    deadline = models.DateField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='opportunities_created')
    approval_status = models.CharField(max_length=12, choices=APPROVAL_CHOICES, default='pending')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='opportunities_approved')
    approved_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['approval_status', 'is_active', 'deadline'], name='opportunity_public_idx'),
            models.Index(fields=['opportunity_type', 'work_mode'], name='opportunity_type_mode_idx'),
        ]

    def clean(self):
        super().clean()
        if self.contact_method == 'url' and not self.application_url:
            raise ValidationError({'application_url': 'Bağlantı ile başvuru için URL zorunludur.'})
        if self.contact_method == 'email' and not self.contact_email:
            raise ValidationError({'contact_email': 'E-posta ile başvuru için adres zorunludur.'})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f'{self.organization}-{self.title}') or 'kariyer-ilani'
            candidate = base
            counter = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{counter}'
                counter += 1
            self.slug = candidate
        self.full_clean(exclude=['technologies'])
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return bool(
            self.is_active
            and self.approval_status == 'approved'
            and (self.deadline is None or self.deadline >= timezone.localdate())
        )

    def get_absolute_url(self):
        return reverse('career:opportunity_detail', kwargs={'slug': self.slug})

    def __str__(self):
        return f'{self.organization} · {self.title}'


class CollaborationRequest(models.Model):
    REQUEST_TYPE_CHOICES = [
        ('internship', 'Stajyer arayışı'),
        ('recruitment', 'İşe alım'),
        ('team', 'Öğrenci/ekip arayışı'),
        ('project', 'Proje iş birliği'),
        ('capstone', 'Bitirme projesi önerisi'),
        ('research', 'Araştırma problemi'),
        ('sponsorship', 'Sponsorluk'),
        ('event', 'Etkinlik desteği'),
        ('speaker', 'Eğitim/konuşmacı talebi'),
        ('academic', 'Akademik iş birliği'),
        ('other', 'Diğer'),
    ]
    CONTACT_CHOICES = [('email', 'E-posta'), ('phone', 'Telefon'), ('video', 'Çevrim içi görüşme')]
    STATUS_CHOICES = [
        ('pending_email', 'E-posta doğrulaması bekleniyor'),
        ('pending_review', 'Yönetici incelemesi bekleniyor'),
        ('approved', 'Onaylandı'),
        ('published', 'Yayımlandı'),
        ('rejected', 'Reddedildi'),
    ]
    CHANNEL_CHOICES = [
        ('internal', 'Yalnızca iç değerlendirme'),
        ('project', 'Proje İlanları'),
        ('career', 'Kariyer'),
        ('event', 'Etkinlik yönetimi'),
    ]

    tracking_number = models.CharField(max_length=24, unique=True, editable=False)
    contact_name = models.CharField(max_length=160, verbose_name='Yetkili adı ve soyadı')
    organization = models.CharField(max_length=180, verbose_name='Şirket/kurum adı')
    job_title = models.CharField(max_length=120, verbose_name='Görevi')
    email = models.EmailField(verbose_name='E-posta')
    phone = models.CharField(max_length=30, blank=True, verbose_name='Telefon')
    website = models.URLField(blank=True, verbose_name='Şirket web sitesi')
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, verbose_name='Talep türü')
    interest_reference = models.CharField(max_length=220, blank=True, verbose_name='İlgilenilen proje veya öğrenci')
    title = models.CharField(max_length=200, verbose_name='Talep başlığı')
    description = models.TextField(verbose_name='Açıklama')
    preferred_contact = models.CharField(max_length=12, choices=CONTACT_CHOICES, default='email', verbose_name='Tercih edilen iletişim yöntemi')
    consent_accepted = models.BooleanField(default=False, verbose_name='KVKK ve iletişim onayı')
    consent_at = models.DateTimeField(blank=True, null=True)
    email_verified_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending_email', db_index=True)
    publication_channel = models.CharField(max_length=12, choices=CHANNEL_CHOICES, default='internal')
    normalized_title = models.CharField(max_length=200, blank=True)
    normalized_description = models.TextField(blank=True)
    expected_output = models.TextField(blank=True, verbose_name='Beklenen çıktı')
    deadline = models.DateField(blank=True, null=True, verbose_name='Son başvuru tarihi')
    assigned_teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_collaboration_requests')
    project_type = models.ForeignKey('projects.ProjectType', on_delete=models.PROTECT, null=True, blank=True)
    categories = models.ManyToManyField(ProjectCategory, blank=True, related_name='collaboration_requests')
    technologies = models.ManyToManyField(Technology, blank=True, related_name='collaboration_requests')
    project_request = models.OneToOneField('projects.ProjectRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_collaboration')
    opportunity = models.OneToOneField(Opportunity, on_delete=models.SET_NULL, null=True, blank=True, related_name='source_collaboration')
    admin_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_collaboration_requests')
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'], name='collab_status_date_idx')]

    def save(self, *args, **kwargs):
        if not self.tracking_number:
            import secrets
            self.tracking_number = f'BST-{timezone.now():%Y}-{secrets.token_hex(4).upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.tracking_number} · {self.organization}'


class MentorshipProfile(models.Model):
    CONTACT_CHOICES = [('email', 'E-posta'), ('linkedin', 'LinkedIn'), ('website', 'Kişisel web sitesi')]

    alumni = models.OneToOneField(Alumni, on_delete=models.CASCADE, related_name='mentorship_profile')
    is_available = models.BooleanField(default=False)
    mentoring_topics = models.ManyToManyField(ProjectCategory, related_name='mentors', blank=True)
    monthly_capacity = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1), MaxValueValidator(20)])
    preferred_contact_method = models.CharField(max_length=12, choices=CONTACT_CHOICES, default='email')
    availability_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['alumni__full_name']

    def contact_value(self):
        if self.preferred_contact_method == 'linkedin':
            return self.alumni.linkedin_url or ''
        if self.preferred_contact_method == 'website':
            return self.alumni.personal_website or ''
        return self.alumni.user.email if self.alumni.user_id else ''

    def __str__(self):
        return f'Mentor: {self.alumni.get_display_name()}'


class MentorshipRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Bekliyor'),
        ('accepted', 'Kabul edildi'),
        ('rejected', 'Reddedildi'),
        ('completed', 'Tamamlandı'),
        ('cancelled', 'İptal edildi'),
    ]

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mentorship_requests')
    mentor = models.ForeignKey(MentorshipProfile, on_delete=models.CASCADE, related_name='requests')
    topic = models.ForeignKey(ProjectCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='mentorship_requests')
    goal = models.CharField(max_length=250)
    message = models.TextField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    mentor_response = models.TextField(blank=True)
    responded_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'mentor'],
                condition=Q(status__in=['pending', 'accepted']),
                name='unique_active_student_mentor_request',
            ),
        ]
        indexes = [models.Index(fields=['mentor', 'status', '-created_at'], name='mentor_request_inbox_idx')]

    def __str__(self):
        return f'{self.student} → {self.mentor}'


class MentorshipReview(models.Model):
    mentorship_request = models.OneToOneField(MentorshipRequest, on_delete=models.CASCADE, related_name='review')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.mentorship_request.status != 'completed':
            raise ValidationError('Yalnızca tamamlanan mentorluk için değerlendirme yapılabilir.')

    def __str__(self):
        return f'{self.mentorship_request} · {self.rating}/5'
