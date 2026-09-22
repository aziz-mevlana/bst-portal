from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
import os
import unicodedata
import uuid

from projects.models import Project

from .storage import capstone_private_storage


def _normalized_submission_filename(filename):
    normalized = unicodedata.normalize('NFKC', str(filename or '')).replace('\\', '/')
    basename = os.path.basename(normalized).replace('\x00', '').strip()
    if not basename:
        return 'dosya'
    if len(basename) <= 255:
        return basename
    stem, extension = os.path.splitext(basename)
    return f'{stem[:255 - len(extension)]}{extension}'


def capstone_submission_file_upload_to(instance, filename):
    return f'submissions/{uuid.uuid4().hex}'


class CapstoneTerm(models.Model):
    class Semester(models.TextChoices):
        FALL = 'FALL', 'Güz'
        SPRING = 'SPRING', 'Bahar'

    academic_year = models.CharField(max_length=9)
    semester = models.CharField(max_length=6, choices=Semester.choices)
    starts_at = models.DateTimeField()
    midterm_at = models.DateTimeField()
    final_at = models.DateTimeField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-academic_year', 'semester']
        constraints = [
            models.UniqueConstraint(
                fields=['academic_year', 'semester'],
                name='unique_capstone_academic_term',
            ),
            models.UniqueConstraint(
                fields=['is_active'],
                condition=Q(is_active=True),
                name='unique_active_capstone_term',
            ),
            models.CheckConstraint(
                condition=Q(starts_at__lt=F('midterm_at')) & Q(midterm_at__lt=F('final_at')),
                name='capstone_term_dates_chronological',
            ),
        ]
        indexes = [
            models.Index(fields=['is_active', 'starts_at'], name='cap_term_active_start_idx'),
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.midterm_at and self.starts_at >= self.midterm_at:
            raise ValidationError({'midterm_at': 'Ara değerlendirme başlangıç tarihinden sonra olmalıdır.'})
        if self.midterm_at and self.final_at and self.midterm_at >= self.final_at:
            raise ValidationError({'final_at': 'Final ara değerlendirme tarihinden sonra olmalıdır.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.academic_year} {self.get_semester_display()}'


class CapstoneEnrollment(models.Model):
    term = models.ForeignKey(
        CapstoneTerm,
        on_delete=models.CASCADE,
        related_name='enrollments',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='capstone_enrollments',
    )
    is_active = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_capstone_enrollments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['term_id', 'student_id']
        constraints = [
            models.UniqueConstraint(
                fields=['term', 'student'],
                name='unique_capstone_term_student',
            ),
        ]
        indexes = [
            models.Index(fields=['term', 'is_active'], name='cap_enroll_term_active_idx'),
        ]

    def clean(self):
        super().clean()
        if self.student_id:
            profile = getattr(self.student, 'profile', None)
            if profile is None or profile.user_type not in {'student', 'staff_student'}:
                raise ValidationError({'student': 'Yalnızca öğrenci rolleri bitirme dönemine kaydedilebilir.'})
            if profile.class_level != '4':
                raise ValidationError({'student': 'Bitirme dönemi kaydı yalnızca 4. sınıf öğrencileri içindir.'})
        if self.approved_by_id and not (self.approved_by.is_staff or self.approved_by.is_superuser):
            raise ValidationError({'approved_by': 'Onaylayan kullanıcı Django yöneticisi olmalıdır.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.term} - {self.student.get_username()}'


class CapstoneProject(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name='capstone',
    )
    term = models.ForeignKey(
        CapstoneTerm,
        on_delete=models.PROTECT,
        related_name='capstone_projects',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['term', 'project_id']
        indexes = [
            models.Index(fields=['term', 'created_at'], name='cap_project_term_date_idx'),
        ]

    def clean(self):
        super().clean()
        if not self.project_id:
            return
        if self.project.project_type.code != 'CAPSTONE':
            raise ValidationError({'project': 'Yalnızca CAPSTONE türündeki projeler bağlanabilir.'})
        if self.project.advisor_id is None:
            raise ValidationError({'project': 'Bitirme projesinin bir danışmanı olmalıdır.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.project.title


class CapstoneCheckpoint(models.Model):
    class Kind(models.TextChoices):
        FIRST_REVIEW = 'FIRST_REVIEW', 'İlk Değerlendirme'
        MIDTERM_REVIEW = 'MIDTERM_REVIEW', 'Ara Değerlendirme'
        POST_MIDTERM_REVIEW = 'POST_MIDTERM_REVIEW', 'Ara Değerlendirme Sonrası'
        FINAL_REVIEW = 'FINAL_REVIEW', 'Final Değerlendirmesi'

    capstone_project = models.ForeignKey(
        CapstoneProject,
        on_delete=models.CASCADE,
        related_name='checkpoints',
    )
    kind = models.CharField(max_length=22, choices=Kind.choices)
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_at', 'kind']
        constraints = [
            models.UniqueConstraint(
                fields=['capstone_project', 'kind'],
                name='unique_capstone_checkpoint_kind',
            ),
        ]
        indexes = [
            models.Index(fields=['capstone_project', 'due_at'], name='cap_checkpoint_due_idx'),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.capstone_project} - {self.get_kind_display()}'


class CapstoneTask(models.Model):
    capstone_project = models.ForeignKey(
        CapstoneProject,
        on_delete=models.CASCADE,
        related_name='tasks',
    )
    checkpoint = models.ForeignKey(
        CapstoneCheckpoint,
        on_delete=models.CASCADE,
        related_name='tasks',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_capstone_tasks',
    )
    title = models.CharField(max_length=200)
    instructions = models.TextField(max_length=5000)
    required_file_count = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_at', 'created_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(required_file_count__gte=1, required_file_count__lte=20),
                name='cap_task_file_count_range',
            ),
        ]
        indexes = [
            models.Index(fields=['checkpoint', 'due_at'], name='cap_task_checkpoint_due_idx'),
            models.Index(fields=['capstone_project', 'due_at'], name='cap_task_project_due_idx'),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.capstone_project_id and self.created_by_id:
            from .policies import can_review_capstone

            if not can_review_capstone(self.created_by, self.capstone_project):
                errors['created_by'] = 'Görevi yalnızca atanmış danışman veya Django yöneticisi oluşturabilir.'
        if self.capstone_project_id and self.checkpoint_id:
            if self.checkpoint.capstone_project_id != self.capstone_project_id:
                errors['checkpoint'] = 'Kontrol noktası aynı bitirme projesine ait olmalıdır.'
            if self.due_at and self.due_at > self.checkpoint.due_at:
                errors['due_at'] = 'Görev tarihi kontrol noktası tarihinden sonra olamaz.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.capstone_project} - {self.title}'


class CapstoneSubmissionAttempt(models.Model):
    task = models.ForeignKey(
        CapstoneTask,
        on_delete=models.CASCADE,
        related_name='submission_attempts',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='capstone_submission_attempts',
    )
    attempt_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
    )
    submitted_at = models.DateTimeField(editable=False)
    is_late = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ['task_id', 'attempt_number']
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'attempt_number'],
                name='unique_capstone_task_attempt',
            ),
            models.CheckConstraint(
                condition=Q(attempt_number__gte=1),
                name='cap_submission_attempt_number_gte_1',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.task_id and self.submitted_by_id:
            from .policies import can_submit_capstone

            if not can_submit_capstone(self.submitted_by, self.task.capstone_project):
                errors['submitted_by'] = 'Teslimi yalnızca bitirme projesinin sahibi öğrenci yapabilir.'

        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values(
                'task_id',
                'submitted_by_id',
                'attempt_number',
                'submitted_at',
                'is_late',
            ).first()
            if original:
                immutable_fields = {
                    'task': self.task_id,
                    'submitted_by': self.submitted_by_id,
                    'attempt_number': self.attempt_number,
                    'submitted_at': self.submitted_at,
                    'is_late': self.is_late,
                }
                changed_fields = [
                    field
                    for field, value in immutable_fields.items()
                    if original[f'{field}_id' if field in {'task', 'submitted_by'} else field] != value
                ]
                if changed_fields:
                    errors['__all__'] = (
                        'Kaydedilmiş teslim denemesinin akademik kayıt alanları değiştirilemez: '
                        f'{", ".join(changed_fields)}.'
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.submitted_at = timezone.now()
            self.is_late = bool(self.task_id and self.submitted_at > self.task.due_at)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.task} - Deneme {self.attempt_number}'


class CapstoneSubmissionFile(models.Model):
    submission_attempt = models.ForeignKey(
        CapstoneSubmissionAttempt,
        on_delete=models.CASCADE,
        related_name='files',
    )
    file = models.FileField(
        storage=capstone_private_storage,
        upload_to=capstone_submission_file_upload_to,
        max_length=100,
    )
    original_name = models.CharField(max_length=255, editable=False)
    size_bytes = models.PositiveBigIntegerField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def clean(self):
        super().clean()
        if not self.pk:
            return

        original = type(self).objects.filter(pk=self.pk).values(
            'submission_attempt_id',
            'file',
            'original_name',
            'size_bytes',
        ).first()
        if not original:
            return

        immutable_fields = {
            'submission_attempt': self.submission_attempt_id,
            'file': self.file.name,
            'original_name': self.original_name,
            'size_bytes': self.size_bytes,
        }
        changed_fields = [
            field
            for field, value in immutable_fields.items()
            if original[
                'submission_attempt_id' if field == 'submission_attempt' else field
            ] != value
        ]
        if changed_fields:
            raise ValidationError({
                '__all__': (
                    'Kaydedilmiş teslim dosyasının akademik kayıt alanları değiştirilemez: '
                    f'{", ".join(changed_fields)}.'
                ),
            })

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.file and self.file.name:
                self.original_name = _normalized_submission_filename(self.file.name)
                self.size_bytes = self.file.size
            else:
                self.original_name = ''
                self.size_bytes = 0
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.original_name


class CapstoneSubmissionReview(models.Model):
    class Decision(models.TextChoices):
        ACCEPTED = 'ACCEPTED', 'Kabul Edildi'
        REVISION_REQUIRED = 'REVISION_REQUIRED', 'Revizyon Gerekli'
        REJECTED = 'REJECTED', 'Reddedildi'

    submission_attempt = models.OneToOneField(
        CapstoneSubmissionAttempt,
        on_delete=models.CASCADE,
        related_name='review',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='capstone_submission_reviews',
    )
    decision = models.CharField(max_length=17, choices=Decision.choices)
    feedback = models.TextField(max_length=5000)
    reviewed_at = models.DateTimeField(editable=False)

    class Meta:
        ordering = ['-reviewed_at']

    def clean(self):
        super().clean()
        errors = {}
        self.feedback = (self.feedback or '').strip()

        if not self.feedback:
            errors['feedback'] = 'Değerlendirme geri bildirimi boş bırakılamaz.'

        if self.submission_attempt_id and self.reviewed_by_id:
            from .policies import can_review_capstone

            capstone_project = self.submission_attempt.task.capstone_project
            if not can_review_capstone(self.reviewed_by, capstone_project):
                errors['reviewed_by'] = (
                    'Değerlendirmeyi yalnızca atanmış aktif danışman veya Django yöneticisi yapabilir.'
                )

        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values(
                'submission_attempt_id',
                'reviewed_by_id',
                'decision',
                'feedback',
                'reviewed_at',
            ).first()
            if original:
                immutable_fields = {
                    'submission_attempt': self.submission_attempt_id,
                    'reviewed_by': self.reviewed_by_id,
                    'decision': self.decision,
                    'feedback': self.feedback,
                    'reviewed_at': self.reviewed_at,
                }
                changed_fields = [
                    field
                    for field, value in immutable_fields.items()
                    if original[
                        f'{field}_id'
                        if field in {'submission_attempt', 'reviewed_by'}
                        else field
                    ] != value
                ]
                if changed_fields:
                    errors['__all__'] = (
                        'Kaydedilmiş teslim değerlendirmesi değiştirilemez: '
                        f'{", ".join(changed_fields)}.'
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.reviewed_at = timezone.now()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.submission_attempt} - {self.get_decision_display()}'
