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
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='completed_capstone_projects', editable=False,
    )

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
    max_score = models.PositiveSmallIntegerField(default=25, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_at', 'kind']
        constraints = [
            models.UniqueConstraint(
                fields=['capstone_project', 'kind'],
                name='unique_capstone_checkpoint_kind',
            ),
            models.CheckConstraint(condition=Q(max_score__gt=0), name='cap_checkpoint_score_positive'),
        ]
        indexes = [
            models.Index(fields=['capstone_project', 'due_at'], name='cap_checkpoint_due_idx'),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, evaluation__isnull=False).exists():
            old = type(self).objects.get(pk=self.pk)
            if old.max_score != self.max_score or old.due_at != self.due_at:
                raise ValidationError('Puanlanmış değerlendirme aşamasının akademik tanımı değiştirilemez.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.capstone_project} - {self.get_kind_display()}'


class CapstoneProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Danışman onayı bekliyor'
        APPROVED = 'APPROVED', 'Onaylandı'
        REJECTED = 'REJECTED', 'Reddedildi'
        WITHDRAWN = 'WITHDRAWN', 'Geri çekildi'

    term = models.ForeignKey(CapstoneTerm, on_delete=models.PROTECT, related_name='proposals')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='capstone_proposals')
    requested_advisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='requested_capstone_proposals')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    advisor_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_capstone_proposals')
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    resulting_capstone_project = models.OneToOneField(CapstoneProject, on_delete=models.PROTECT, null=True, blank=True, related_name='source_proposal')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(
            fields=['term', 'student'], condition=Q(status='PENDING'), name='unique_pending_capstone_proposal'
        )]
        indexes = [models.Index(fields=['requested_advisor', 'status'], name='cap_proposal_advisor_idx')]

    def clean(self):
        super().clean()
        if self._state.adding and self.status == self.Status.PENDING:
            from accounts.policies import role_of
            from .policies import is_capstone_eligible_student
            if not self.term_id or not self.term.is_active or not is_capstone_eligible_student(self.student, self.term):
                raise ValidationError('Aktif döneme kayıtlı 4. sınıf öğrenci gereklidir.')
            if not self.requested_advisor.is_active or role_of(self.requested_advisor) != 'teacher' or self.requested_advisor.is_staff:
                raise ValidationError({'requested_advisor': 'Aktif bir akademisyen seçilmelidir.'})
            if CapstoneProject.objects.filter(project__created_by_id=self.student_id).exclude(
                project__development_status__in=['cancelled', 'completed']
            ).exists():
                raise ValidationError('Öğrencinin zaten aktif bitirme projesi var.')
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            for field in ('term_id', 'student_id', 'requested_advisor_id', 'title', 'description', 'resulting_capstone_project_id'):
                if field != 'resulting_capstone_project_id' and getattr(old, field) != getattr(self, field):
                    raise ValidationError('Kaydedilmiş teklifin akademik bilgileri değiştirilemez.')
            if old.status != self.Status.PENDING and any(getattr(old, field) != getattr(self, field) for field in (
                'status', 'advisor_note', 'reviewed_by_id', 'reviewed_at', 'resulting_capstone_project_id'
            )):
                raise ValidationError('Sonuçlanmış teklif değiştirilemez.')
        if self.status == self.Status.APPROVED and not self.resulting_capstone_project_id:
            raise ValidationError({'resulting_capstone_project': 'Onaylanan teklif projeye bağlanmalıdır.'})
        if self.status == self.Status.APPROVED and self.resulting_capstone_project_id:
            capstone_project = self.resulting_capstone_project
            if (capstone_project.term_id != self.term_id or
                    capstone_project.project.created_by_id != self.student_id or
                    capstone_project.project.advisor_id != self.requested_advisor_id):
                raise ValidationError({'resulting_capstone_project': 'Proje teklifin öğrenci, danışman ve dönemiyle eşleşmelidir.'})
        if self.status == self.Status.REJECTED and not (self.advisor_note or '').strip():
            raise ValidationError({'advisor_note': 'Ret gerekçesi zorunludur.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Akademik teklif geçmişi silinemez.')


class CapstoneCheckpointEvaluation(models.Model):
    checkpoint = models.OneToOneField(CapstoneCheckpoint, on_delete=models.PROTECT, related_name='evaluation')
    evaluated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='capstone_checkpoint_evaluations')
    score = models.PositiveSmallIntegerField()
    feedback = models.TextField(max_length=5000)
    evaluated_at = models.DateTimeField(editable=False)

    def clean(self):
        super().clean()
        if self.pk:
            raise ValidationError('Akademik değerlendirme değiştirilemez.')
        self.feedback = (self.feedback or '').strip()
        if not self.feedback:
            raise ValidationError({'feedback': 'Akademik geri bildirim zorunludur.'})
        if self.checkpoint_id:
            from .policies import can_review_capstone
            from .workflow import CheckpointProgress, get_checkpoint_progress
            if self.evaluated_by_id and not can_review_capstone(self.evaluated_by, self.checkpoint.capstone_project):
                raise ValidationError({'evaluated_by': 'Bu değerlendirme aşamasını puanlama yetkiniz yok.'})
            if get_checkpoint_progress(self.checkpoint) != CheckpointProgress.COMPLETED:
                raise ValidationError('Değerlendirme aşamasının tüm görevleri kabul edilmelidir.')
            if self.score is not None and self.score > self.checkpoint.max_score:
                raise ValidationError({'score': 'Puan üst sınırı aşamaz.'})

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Akademik değerlendirme değiştirilemez.')
        self.evaluated_at = timezone.now()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Akademik değerlendirme silinemez.')


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
                errors['checkpoint'] = 'Değerlendirme aşaması aynı bitirme projesine ait olmalıdır.'
            if self.due_at and self.due_at > self.checkpoint.due_at:
                errors['due_at'] = 'Görev tarihi değerlendirme aşamasının tarihinden sonra olamaz.'
            if self.checkpoint.pk and CapstoneCheckpointEvaluation.objects.filter(checkpoint=self.checkpoint).exists():
                errors['checkpoint'] = 'Akademik puanlaması yapılmış değerlendirme aşamasına görev eklenemez veya görev değiştirilemez.'
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
