import re
import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse
from urllib.parse import urlparse
from PIL import Image


class ProjectCategory(models.Model):
    """Presentation tag that describes a project's subject area."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=60, blank=True)
    color = models.CharField(max_length=7, default='#3B82F6', help_text='Hex color code')
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Project Category'
        verbose_name_plural = 'Project Categories'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            base = slugify(self.name) or 'kategori'
            candidate = base
            counter = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{counter}'
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class Technology(models.Model):
    """Technologies used in projects."""

    GROUP_CHOICES = [
        ('frontend', 'Frontend'), ('backend', 'Backend'), ('mobile', 'Mobil'),
        ('ai_ml', 'Yapay zekâ ve makine öğrenmesi'), ('data_science', 'Veri bilimi'),
        ('database', 'Veritabanı'), ('devops', 'DevOps'), ('cloud', 'Bulut'),
        ('game', 'Oyun geliştirme'), ('cybersecurity', 'Siber güvenlik'),
        ('iot', 'IoT ve gömülü sistemler'), ('robotics', 'Robotik'),
        ('design', 'Tasarım ve prototipleme'), ('testing', 'Test araçları'), ('other', 'Diğer'),
    ]

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    group = models.CharField(max_length=24, choices=GROUP_CHOICES, default='other')
    icon = models.CharField(max_length=50, blank=True, help_text='Font Awesome icon class')
    color = models.CharField(max_length=7, default='#10B981', help_text='Hex color code')
    description = models.TextField(blank=True)
    official_url = models.URLField(blank=True)
    aliases = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Technology'
        verbose_name_plural = 'Technologies'
        ordering = ['group', 'sort_order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            base = slugify(self.name) or 'teknoloji'
            candidate = base
            counter = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{counter}'
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class Team(models.Model):
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    description = models.TextField(blank=True)
    leader = models.ForeignKey(User, on_delete=models.PROTECT, related_name='led_teams')
    members = models.ManyToManyField(User, through='TeamMembership', related_name='bst_teams', blank=True)
    technologies = models.ManyToManyField(Technology, related_name='teams', blank=True)
    work_areas = models.ManyToManyField(ProjectCategory, related_name='teams', blank=True)
    recruitment_open = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'ekip'
            candidate = base
            counter = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{counter}'
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('projects:team_detail', kwargs={'slug': self.slug})


class TeamRole(models.TextChoices):
    TEAM_LEAD = 'team_lead', 'Ekip Lideri'
    TECH_LEAD = 'tech_lead', 'Teknik Lider'
    PRODUCT_MANAGER = 'product_manager', 'Ürün Yöneticisi'
    PROJECT_MANAGER = 'project_manager', 'Proje Yöneticisi'
    BUSINESS_ANALYST = 'business_analyst', 'İş / Sistem Analisti'
    UI_UX = 'ui_ux', 'UI/UX Tasarımcısı'
    FRONTEND = 'frontend', 'Frontend Geliştirici'
    BACKEND = 'backend', 'Backend Geliştirici'
    FULLSTACK = 'fullstack', 'Full-stack Geliştirici'
    MOBILE = 'mobile', 'Mobil Uygulama Geliştiricisi'
    AI_ML = 'ai_ml', 'Yapay Zekâ / Makine Öğrenmesi'
    DATA_SCIENCE = 'data_science', 'Veri Bilimci / Analisti'
    DATA_ENGINEERING = 'data_engineering', 'Veri Mühendisi'
    DATABASE = 'database', 'Veritabanı Uzmanı'
    DEVOPS_CLOUD = 'devops_cloud', 'DevOps / Bulut Uzmanı'
    CYBERSECURITY = 'cybersecurity', 'Siber Güvenlik Uzmanı'
    QA_TEST = 'qa_test', 'Test / Kalite Güvence'
    EMBEDDED_IOT = 'embedded_iot', 'Gömülü Sistemler / IoT'
    GAME = 'game', 'Oyun Geliştiricisi'
    BLOCKCHAIN = 'blockchain', 'Blockchain / Web3 Geliştiricisi'
    RESEARCH = 'research', 'Araştırma / Akademik Destek'
    DOCUMENTATION = 'documentation', 'Teknik Dokümantasyon'
    GENERAL = 'general', 'Genel Ekip Üyesi'


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='membership_records')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_memberships')
    role = models.CharField(max_length=120, choices=TeamRole.choices, default=TeamRole.GENERAL)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['joined_at']
        constraints = [models.UniqueConstraint(fields=['team', 'user'], name='unique_team_membership')]


class TeamInvitation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Bekliyor'), ('accepted', 'Kabul edildi'),
        ('rejected', 'Reddedildi'), ('cancelled', 'İptal edildi'),
    ]
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invitations')
    invited_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_invitations')
    invited_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sent_team_invitations')
    proposed_role = models.CharField(max_length=120, choices=TeamRole.choices, default=TeamRole.GENERAL)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'invited_user'], condition=models.Q(status='pending'), name='unique_pending_team_invite'
            ),
        ]


class TeamOpenRole(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='open_roles')
    title = models.CharField(max_length=120, choices=TeamRole.choices)
    description = models.TextField(blank=True)
    required_technologies = models.ManyToManyField(Technology, related_name='team_open_roles', blank=True)
    is_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_open', 'title']


class ProjectType(models.Model):
    """Stable project taxonomy, independent from presentation categories."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=60, blank=True)
    color = models.CharField(max_length=7, default='#3B82F6')
    requires_advisor = models.BooleanField(default=False)
    requires_course = models.BooleanField(default=False)
    requires_organization = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [models.Index(fields=['is_active', 'sort_order'], name='projtype_active_sort_idx')]

    def save(self, *args, **kwargs):
        normalized_code = self.code.strip().upper()
        if self.pk:
            previous_code = type(self).objects.filter(pk=self.pk).values_list('code', flat=True).first()
            if previous_code and previous_code != normalized_code:
                raise ValidationError({'code': 'Proje tipi kodu oluşturulduktan sonra değiştirilemez.'})
        self.code = normalized_code
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        """Project types are retired instead of being physically deleted."""

        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])

    def __str__(self):
        return self.name


class ProjectProgram(models.Model):
    PROGRAM_TYPE_CHOICES = [
        ('support', 'Destek Programı'),
        ('competition', 'Yarışma'),
        ('hackathon', 'Hackathon'),
        ('incubation', 'Kuluçka Programı'),
        ('grant', 'Hibe Programı'),
        ('other', 'Diğer'),
    ]

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    program_type = models.CharField(max_length=20, choices=PROGRAM_TYPE_CHOICES, default='other')
    description = models.TextField(blank=True)
    official_url = models.URLField(blank=True)
    project_types = models.ManyToManyField(ProjectType, related_name='programs', blank=True)
    starts_at = models.DateField(blank=True, null=True)
    ends_at = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', 'sort_order', 'name']

    def __str__(self):
        return self.name


class ProjectRequest(models.Model):
    """An academic project announcement that students can apply to."""

    SEMESTER_CHOICES = [
        ('fall', 'Güz'),
        ('spring', 'Bahar'),
        ('summer', 'Yaz'),
    ]
    REQUEST_STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('open', 'Başvuruya Açık'),
        ('reviewing', 'Değerlendiriliyor'),
        ('student_selected', 'Öğrenci Seçildi'),
        ('closed', 'Kapandı'),
        ('cancelled', 'İptal Edildi'),
    ]
    SUPERVISION_CHOICES = [
        ('unsupervised', 'Denetimsiz'),
        ('supervised', 'Denetimli'),
    ]

    title = models.CharField(max_length=200)
    project_type = models.ForeignKey(
        ProjectType,
        on_delete=models.PROTECT,
        related_name='requests',
    )
    course = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True, null=True, verbose_name='Açıklama')
    requirements = models.TextField(blank=True, null=True, verbose_name='Gerekli Koşullar')
    expected_output = models.TextField(blank=True, verbose_name='Beklenen Çıktı')
    estimated_duration = models.CharField(max_length=100, blank=True, verbose_name='Tahmini Süre')
    semester = models.CharField(max_length=10, choices=SEMESTER_CHOICES, blank=True, null=True, verbose_name='Dönem')
    year = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Yıl')
    deadline = models.DateField(blank=True, null=True, verbose_name='Son Başvuru Tarihi')
    team_size = models.PositiveSmallIntegerField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default='draft', verbose_name='Durum')
    supervision_type = models.CharField(max_length=15, choices=SUPERVISION_CHOICES, default='unsupervised', verbose_name='Denetim Türü')
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='project_requests')
    categories = models.ManyToManyField(ProjectCategory, related_name='project_requests', blank=True, verbose_name='Kategoriler')
    technologies = models.ManyToManyField(Technology, related_name='project_requests', blank=True, verbose_name='Teknolojiler')
    created_project = models.OneToOneField(
        'Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originating_request',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Project Request'
        verbose_name_plural = 'Project Requests'
        indexes = [models.Index(fields=['status', 'deadline'], name='request_status_deadline_idx')]

    def __str__(self):
        if self.teacher:
            return f'{self.title} - {self.teacher.get_full_name()}'
        return self.title

    def get_semester_display_full(self):
        return self.get_semester_display() if self.semester else None

    @property
    def is_past_deadline(self):
        return bool(self.deadline and timezone.now().date() > self.deadline)

    @property
    def accepts_applications(self):
        return self.status == 'open' and not self.is_past_deadline and self.created_project_id is None


class Project(models.Model):
    """A project case study and its workflow state."""

    # Kept temporarily for backwards compatibility while old screens are migrated.
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('in_review', 'Değerlendirme Aşamasında'),
        ('approved', 'Fikir Onaylandı'),
        ('in_progress', 'Devam Ediyor'),
        ('completed', 'Tamamlandı'),
    ]
    CREATION_SOURCE_CHOICES = [
        ('STUDENT_IDEA', 'Öğrenci Fikri'),
        ('ACADEMIC_REQUEST', 'Akademisyen İlanı'),
        ('COURSE_ASSIGNMENT', 'Ders Kapsamında Verilen Görev'),
        ('DEPARTMENT_COMMUNITY', 'Bölüm veya Topluluk İhtiyacı'),
        ('COMPANY_ORGANIZATION', 'Şirket veya Kurum Talebi'),
        ('EXTERNAL_CALL', 'Yarışma veya Dış Çağrı'),
        ('LEGACY', 'Eski Sistem Kaydı'),
    ]
    APPROVAL_STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('pending', 'Onay Bekliyor'),
        ('revision_requested', 'Revizyon İstendi'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
    ]
    DEVELOPMENT_STATUS_CHOICES = [
        ('idea', 'Fikir'),
        ('planning', 'Planlama'),
        ('in_progress', 'Geliştiriliyor'),
        ('on_hold', 'Beklemede'),
        ('completed', 'Tamamlandı'),
        ('cancelled', 'İptal Edildi'),
    ]
    VISIBILITY_CHOICES = [
        ('private', 'Gizli'),
        ('unlisted', 'Bağlantıya Özel'),
        ('public', 'Herkese Açık'),
        ('archived', 'Arşivlendi'),
    ]

    project_request = models.ForeignKey(
        ProjectRequest,
        on_delete=models.SET_NULL,
        related_name='projects',
        null=True,
        blank=True,
    )
    project_type = models.ForeignKey(
        ProjectType,
        on_delete=models.PROTECT,
        related_name='projects',
    )
    creation_source = models.CharField(max_length=24, choices=CREATION_SOURCE_CHOICES, default='STUDENT_IDEA')
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    title = models.CharField(max_length=200)
    advisor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='advised_projects')
    description = models.TextField(blank=True, null=True)
    expected_output = models.TextField(blank=True)
    team = models.ManyToManyField(User, related_name='projects', blank=True)
    team_entity = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='projects', verbose_name='Ekip'
    )
    project_link = models.URLField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_private = models.BooleanField(default=True)
    approval_status = models.CharField(max_length=24, choices=APPROVAL_STATUS_CHOICES, default='draft')
    development_status = models.CharField(max_length=24, choices=DEVELOPMENT_STATUS_CHOICES, default='idea')
    visibility = models.CharField(max_length=12, choices=VISIBILITY_CHOICES, default='private')
    categories = models.ManyToManyField(ProjectCategory, related_name='projects', blank=True)
    technologies = models.ManyToManyField(Technology, related_name='projects', blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Project'
        verbose_name_plural = 'Projects'
        indexes = [
            models.Index(fields=['visibility', 'development_status'], name='project_visibility_dev_idx'),
            models.Index(fields=['project_type', 'creation_source'], name='project_type_source_idx'),
            models.Index(fields=['approval_status', '-created_at'], name='project_approval_date_idx'),
        ]

    def __str__(self):
        return f'{self.title} - {self.created_by.get_full_name()}'

    def get_absolute_url(self):
        return reverse('projects:project_public_detail', kwargs={'slug': self.slug})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or 'proje'
            candidate = base
            counter = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{counter}'
                counter += 1
            self.slug = candidate
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'slug'}
        super().save(*args, **kwargs)

    @property
    def cover_media(self):
        return next((item for item in self.media.all() if item.is_cover), None)


class ProjectProgramParticipation(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='program_participations')
    program = models.ForeignKey(ProjectProgram, on_delete=models.PROTECT, related_name='participations')
    year = models.PositiveSmallIntegerField(blank=True, null=True)
    category = models.CharField(max_length=150, blank=True)
    application_status = models.CharField(max_length=100, blank=True)
    result = models.CharField(max_length=200, blank=True)
    award = models.CharField(max_length=200, blank=True)
    external_url = models.URLField(blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'program'], name='unique_project_program')]

    def __str__(self):
        return f'{self.project} / {self.program}'


def validate_project_upload_size(upload):
    max_size = 20 * 1024 * 1024
    if upload.size > max_size:
        raise ValidationError('Proje dosyaları en fazla 20 MB olabilir.')


def project_media_upload_to(instance, filename):
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    return f'projects/media/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{extension}'


def validate_project_image(upload):
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError('Proje görselleri en fazla 5 MB olabilir.')
    try:
        with Image.open(upload) as image:
            image.verify()
            image_format = (image.format or '').upper()
    except Exception as exc:
        raise ValidationError('Geçerli bir JPG, PNG veya WEBP görseli yükleyin.') from exc
    finally:
        upload.seek(0)
    if image_format not in {'JPEG', 'PNG', 'WEBP'}:
        raise ValidationError('Yalnızca JPG/JPEG, PNG veya WEBP görsel yükleyebilirsiniz.')


def detect_project_upload_type(upload):
    position = 0
    try:
        position = upload.tell() if hasattr(upload, 'tell') else 0
        upload.seek(0)
        header = upload.read(32)
    finally:
        upload.seek(position)
    if header.startswith(b'\xff\xd8\xff'):
        return 'image'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'image'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'image'
    if header.startswith(b'%PDF-'):
        return 'document'
    if len(header) >= 12 and header[4:8] == b'ftyp':
        return 'video'
    if header.startswith(b'\x1aE\xdf\xa3'):
        return 'video'
    return None


def validate_project_upload_content(upload):
    detected = detect_project_upload_type(upload)
    if detected is None:
        raise ValidationError('Dosya içeriği desteklenen görsel, video veya PDF biçimiyle eşleşmiyor.')
    claimed = getattr(upload, 'content_type', '')
    allowed_mime = {
        'image': {'image/jpeg', 'image/png', 'image/webp', 'image/gif'},
        'video': {'video/mp4', 'video/webm'},
        'document': {'application/pdf'},
    }
    if claimed and claimed not in allowed_mime[detected]:
        raise ValidationError('Dosyanın MIME türü ile içeriği eşleşmiyor.')
    if detected == 'document':
        position = upload.tell() if hasattr(upload, 'tell') else 0
        try:
            upload.seek(max(0, upload.size - 2048))
            trailer = upload.read(2048)
        finally:
            upload.seek(position)
        if b'%%EOF' not in trailer:
            raise ValidationError('Geçerli ve tamamlanmış bir PDF dosyası yükleyin.')


class ProjectCaseStudy(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='case_study')
    summary = models.TextField(blank=True, verbose_name='Kısa Proje Özeti')
    problem = models.TextField(blank=True, verbose_name='Çözülen Problem')
    solution = models.TextField(blank=True, verbose_name='Geliştirilen Çözüm')
    architecture = models.TextField(blank=True, verbose_name='Teknik Mimari')
    measurable_results = models.TextField(blank=True, verbose_name='Ölçülebilir Sonuçlar')
    future_developments = models.TextField(blank=True, verbose_name='Gelecek Geliştirmeler')
    demo_url = models.URLField(blank=True, verbose_name='Canlı Demo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Vaka çalışması: {self.project.title}'


class ProjectWritingSuggestion(models.Model):
    STATUS_CHOICES = [
        ('preview', 'Ön izlemede'),
        ('applied', 'Uygulandı'),
        ('rejected', 'Reddedildi'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='writing_suggestions')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_writing_suggestions')
    original_text = models.TextField()
    suggested_fields = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='preview')
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['project', 'status', '-created_at'], name='writing_project_status_idx')]

    def __str__(self):
        return f'{self.project.title} / {self.get_status_display()}'


class ProjectRepository(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='repository')
    repository_path = models.CharField(max_length=201, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project_id']

    @staticmethod
    def parse_repository_path(value):
        value = (value or '').strip()
        if '://' in value or value.startswith('//'):
            raise ValidationError('Yalnızca owner/repository biçimini girin; tam URL kullanmayın.')
        parts = [part for part in value.strip('/').split('/') if part]
        if len(parts) != 2:
            raise ValidationError('GitHub repository değeri owner/repository biçiminde olmalıdır.')
        owner, name = parts
        valid = re.compile(r'^[A-Za-z0-9_.-]+$')
        if not owner or not name or not valid.fullmatch(owner) or not valid.fullmatch(name):
            raise ValidationError('GitHub kullanıcı veya depo adı geçersiz.')
        return owner, name

    def clean(self):
        super().clean()
        if not self.repository_path:
            return
        owner, name = self.parse_repository_path(self.repository_path)
        self.repository_path = f'{owner}/{name}'

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.repository_path

    @property
    def owner(self):
        return self.repository_path.split('/', 1)[0]

    @property
    def name(self):
        return self.repository_path.split('/', 1)[1] if '/' in self.repository_path else ''

    @property
    def repository_url(self):
        return f'https://github.com/{self.repository_path}'


class ProjectMedia(models.Model):
    MEDIA_TYPE_CHOICES = [
        ('image', 'Proje Görseli'),
        ('cover_image', 'Kapak Görseli'),
        ('project_logo', 'Proje Logosu'),
        ('video', 'Video'),
        ('demo', 'Demo'),
        ('document', 'Doküman'),
        ('pitch_deck', 'Yatırımcı Sunumu'),
        ('documentation', 'Proje Dokümantasyonu'),
    ]
    SAFE_VIDEO_HOSTS = {
        'youtube.com', 'www.youtube.com', 'youtu.be',
        'vimeo.com', 'www.vimeo.com', 'player.vimeo.com',
    }

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='media')
    media_type = models.CharField(max_length=16, choices=MEDIA_TYPE_CHOICES)
    file = models.FileField(
        upload_to=project_media_upload_to,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=['jpg', 'jpeg', 'png', 'webp', 'gif', 'pdf', 'mp4', 'webm']
            ),
            validate_project_upload_size,
            validate_project_upload_content,
        ],
    )
    external_url = models.URLField(blank=True)
    caption = models.CharField(max_length=240, blank=True)
    alt_text = models.CharField(max_length=240, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    is_public = models.BooleanField(default=True, verbose_name='Herkese Açık')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['project'],
                condition=models.Q(is_cover=True),
                name='one_cover_per_project',
            ),
            models.UniqueConstraint(
                fields=['project', 'media_type'],
                condition=models.Q(media_type__in=['cover_image', 'project_logo', 'pitch_deck', 'documentation']),
                name='one_project_asset_per_type',
            ),
        ]

    def clean(self):
        super().clean()
        if not self.file and not self.external_url:
            raise ValidationError('Bir dosya veya güvenli harici bağlantı eklemelisiniz.')
        if self.media_type == 'video' and self.external_url:
            parsed = urlparse(self.external_url)
            if parsed.scheme != 'https' or parsed.hostname not in self.SAFE_VIDEO_HOSTS:
                raise ValidationError({'external_url': 'Video için yalnızca HTTPS YouTube veya Vimeo bağlantısı kullanılabilir.'})
        if self.media_type in {'cover_image', 'project_logo', 'pitch_deck', 'documentation'} and self.external_url:
            raise ValidationError({'external_url': 'Bu alan için harici bağlantı değil, dosya yüklemelisiniz.'})
        if self.media_type in {'image', 'cover_image', 'project_logo'}:
            if self.external_url:
                raise ValidationError({'external_url': 'Proje görselleri güvenli dosya olarak yüklenmelidir.'})
            if self.file:
                validate_project_image(self.file)
        if self.external_url and '<' in self.external_url:
            raise ValidationError({'external_url': 'HTML veya iframe kodu değil, yalnızca bağlantı girin.'})
        if self.is_cover and self.media_type not in {'image', 'cover_image'}:
            raise ValidationError({'is_cover': 'Yalnızca görseller kapak olarak seçilebilir.'})
        if self.media_type == 'cover_image':
            self.is_cover = True
        if self.media_type != 'pitch_deck':
            self.is_public = True
        if self.file:
            detected_type = detect_project_upload_type(self.file)
            allowed_types = {
                'image': {'image'},
                'cover_image': {'image'},
                'project_logo': {'image'},
                'video': {'video'},
                'document': {'document'},
                'pitch_deck': {'document'},
                'documentation': {'document'},
                'demo': {'image', 'video', 'document'},
            }
            if detected_type not in allowed_types[self.media_type]:
                raise ValidationError({'file': 'Dosya içeriği seçilen medya türüyle eşleşmiyor.'})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_cover:
                list(
                    type(self).objects.select_for_update()
                    .filter(project=self.project, is_cover=True)
                    .exclude(pk=self.pk)
                    .values_list('pk', flat=True)
                )
                type(self).objects.filter(
                    project=self.project, is_cover=True
                ).exclude(pk=self.pk).update(is_cover=False)
            close_after_validation = bool(
                self.file and getattr(self.file, '_committed', False) and self.file.closed
            )
            try:
                self.full_clean()
            finally:
                if close_after_validation:
                    self.file.close()
            super().save(*args, **kwargs)

    def __str__(self):
        return self.caption or f'{self.project.title} / {self.get_media_type_display()}'


class ProjectContribution(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='contributions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_contributions')
    role = models.CharField(max_length=120)
    contribution_description = models.TextField()
    verified_by_owner = models.BooleanField(default=False)
    verified_by_advisor = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'user'], name='unique_project_contributor'),
        ]

    @property
    def is_verified(self):
        if self.project.advisor_id:
            return self.verified_by_owner and self.verified_by_advisor
        return self.verified_by_owner

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} / {self.role}'


class ProjectAchievement(models.Model):
    ACHIEVEMENT_TYPE_CHOICES = [
        ('award', 'Ödül'),
        ('finalist', 'Finalist'),
        ('ranking', 'Derece'),
        ('funded', 'Destek Almaya Hak Kazandı'),
        ('publication', 'Yayın'),
        ('exhibition', 'Sergileme'),
        ('other', 'Diğer'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='achievements')
    title = models.CharField(max_length=200)
    organization = models.CharField(max_length=200, blank=True)
    achievement_type = models.CharField(max_length=16, choices=ACHIEVEMENT_TYPE_CHOICES)
    date = models.DateField(blank=True, null=True)
    description = models.TextField(blank=True)
    certificate_url = models.URLField(blank=True)
    evidence_file = models.FileField(
        upload_to='projects/achievements/%Y/%m/',
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp', 'pdf']),
            validate_project_upload_size,
            validate_project_upload_content,
        ],
    )
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='verified_project_achievements',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return self.title


class ProjectView(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='view_records')
    viewer = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='project_views')
    session_hash = models.CharField(max_length=64)
    date_bucket = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'session_hash', 'date_bucket'],
                name='unique_daily_project_view',
            ),
        ]
        indexes = [models.Index(fields=['project', '-created_at'], name='project_view_date_idx')]


class ProjectSave(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='saves')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_projects')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['project', 'user'], name='unique_saved_project'),
        ]


class ProjectLike(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='liked_projects')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['project', 'user'], name='unique_project_like')]


class ProjectFeature(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='feature_periods')
    starts_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    selected_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='selected_project_features'
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        indexes = [models.Index(fields=['is_active', 'starts_at', 'ends_at'], name='feature_active_dates_idx')]

    def clean(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'Bitiş zamanı başlangıç zamanından sonra olmalıdır.'})

    @property
    def is_current(self):
        now = timezone.now()
        return bool(
            self.is_active
            and (self.starts_at is None or self.starts_at <= now)
            and (self.ends_at is None or self.ends_at >= now)
        )

    def __str__(self):
        return f'Öne çıkan: {self.project.title}'


class ProjectRequestApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Bekliyor'),
        ('accepted', 'Kabul Edildi'),
        ('rejected', 'Reddedildi'),
        ('withdrawn', 'Geri Çekildi'),
    ]

    project_request = models.ForeignKey(ProjectRequest, on_delete=models.CASCADE, related_name='applications')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_request_applications')
    motivation = models.TextField()
    proposed_approach = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_project_applications',
    )
    review_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['project_request', 'student'],
                name='unique_student_request_application',
            ),
        ]
        indexes = [models.Index(fields=['project_request', 'status'], name='request_app_status_idx')]

    def mark_reviewed(self, reviewer, status, note=''):
        self.status = status
        self.reviewed_by = reviewer
        self.review_note = note
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'review_note', 'reviewed_at', 'updated_at'])

    def __str__(self):
        student_name = self.student.get_full_name() or self.student.username
        return f'{self.project_request} - {student_name}'


class ProjectFeedback(models.Model):
    """Teacher feedback for supervised projects."""

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='feedback')
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_feedbacks')
    content = models.TextField(verbose_name='Geri Bildirim')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Project Feedback'
        verbose_name_plural = 'Project Feedbacks'

    def __str__(self):
        return f'Feedback for {self.project.title} by {self.teacher.get_full_name()}'


class ProjectUpdate(models.Model):
    """Updates for projects."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='updates')
    title = models.CharField(max_length=200, blank=True, null=True)
    version = models.CharField(max_length=40, blank=True)
    description = models.TextField(default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='project_updates')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Project Update'
        verbose_name_plural = 'Project Updates'

    def __str__(self):
        return f'Update for {self.project.title} at {self.created_at}'


class ProjectComment(models.Model):
    """Comments on projects."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_comments')
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, related_name='replies',
        blank=True, null=True, verbose_name='Yanıtlanan yorum',
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Project Comment'
        verbose_name_plural = 'Project Comments'

    def __str__(self):
        return f'Comment by {self.author.get_full_name()} on {self.project.title}'

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.parent_id == self.pk or self.parent.parent_id:
                raise ValidationError({'parent': 'Yanıtlar doğrudan ana yoruma eklenmelidir.'})
            if self.parent.project_id != self.project_id:
                raise ValidationError({'parent': 'Başka bir projenin yorumuna yanıt verilemez.'})
