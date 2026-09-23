"""Shared advisor plans and per-student academic records.

Legacy CAPSTONE checkpoints, submissions, and evaluations remain in models.py.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .storage import capstone_private_storage


def academic_private_file_path(instance, filename):
    return f'academic/{instance._meta.model_name}/{uuid.uuid4().hex}'


class CapstonePlan(models.Model):
    term = models.ForeignKey('capstone.CapstoneTerm', on_delete=models.PROTECT, related_name='academic_plans')
    advisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='capstone_plans')
    title = models.CharField(max_length=200, default='Bitirme Projesi Kontrol Planı')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['term', 'advisor'], name='unique_capstone_advisor_term_plan')]

    def __str__(self):
        return f'{self.advisor} · {self.term}'


class CapstonePlanCheckpoint(models.Model):
    plan = models.ForeignKey(CapstonePlan, on_delete=models.PROTECT, related_name='definitions')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField()
    due_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['plan', 'order'], name='unique_capstone_plan_checkpoint_order')]

    def delete(self, *args, **kwargs):
        if self.student_progress.exists() or self.literature_versions.exists() or self.help_requests.exists() or self.meeting_requests.exists():
            raise ValidationError('Geçmişi bulunan kontrol noktası silinemez; pasife alınmalıdır.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.title


class CapstoneChecklistItem(models.Model):
    checkpoint = models.ForeignKey(CapstonePlanCheckpoint, on_delete=models.PROTECT, related_name='expectations')
    title = models.CharField(max_length=300)
    order = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['checkpoint', 'order'], name='unique_capstone_expectation_order')]


class CapstoneStudentCheckpoint(models.Model):
    capstone_project = models.ForeignKey('capstone.CapstoneProject', on_delete=models.PROTECT, related_name='academic_progress')
    checkpoint = models.ForeignKey(CapstonePlanCheckpoint, on_delete=models.PROTECT, related_name='student_progress')
    override_due_at = models.DateTimeField(null=True, blank=True)
    extension_reason = models.TextField(blank=True)
    extension_changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    extension_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['capstone_project', 'checkpoint'], name='unique_capstone_student_checkpoint')]

    def clean(self):
        if self.capstone_project_id and self.checkpoint_id:
            if self.capstone_project.term_id != self.checkpoint.plan.term_id or self.capstone_project.project.advisor_id != self.checkpoint.plan.advisor_id:
                raise ValidationError('Kontrol noktası bu öğrencinin danışmanlık planına ait değil.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def due_at(self):
        return self.override_due_at or self.checkpoint.due_at


class CapstoneChecklistTick(models.Model):
    progress = models.ForeignKey(CapstoneStudentCheckpoint, on_delete=models.PROTECT, related_name='ticks')
    item = models.ForeignKey(CapstoneChecklistItem, on_delete=models.PROTECT, related_name='student_ticks')
    is_checked = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['progress', 'item'], name='unique_capstone_student_expectation')]

    def clean(self):
        if self.progress_id and self.item_id and self.progress.checkpoint_id != self.item.checkpoint_id:
            raise ValidationError('Beklenenler aynı kontrol noktasına ait olmalıdır.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CapstoneAcademicSubmission(models.Model):
    progress = models.ForeignKey(CapstoneStudentCheckpoint, on_delete=models.PROTECT, related_name='submissions')
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    attempt_number = models.PositiveSmallIntegerField()
    note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(editable=False)
    is_late = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ['attempt_number', 'pk']
        constraints = [models.UniqueConstraint(fields=['progress', 'attempt_number'], name='unique_capstone_academic_attempt'),
                       models.CheckConstraint(condition=Q(attempt_number__gt=0), name='positive_capstone_academic_attempt')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Teslim geçmişi değiştirilemez.')
        self.submitted_at = timezone.now()
        self.is_late = self.submitted_at > self.progress.due_at
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Teslim geçmişi silinemez.')


class AcademicPrivateFile(models.Model):
    file = models.FileField(storage=capstone_private_storage, upload_to=academic_private_file_path, max_length=120)
    original_name = models.CharField(max_length=255, editable=False)
    size_bytes = models.PositiveBigIntegerField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Akademik dosya geçmişi değiştirilemez.')
        from .models import _normalized_submission_filename
        self.original_name = _normalized_submission_filename(self.file.name)
        self.size_bytes = self.file.size
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Akademik dosya geçmişi silinemez.')


class CapstoneAcademicSubmissionFile(AcademicPrivateFile):
    submission = models.ForeignKey(CapstoneAcademicSubmission, on_delete=models.PROTECT, related_name='files')


class CapstoneAcademicSubmissionLink(models.Model):
    submission = models.ForeignKey(CapstoneAcademicSubmission, on_delete=models.PROTECT, related_name='links')
    url = models.URLField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Teslim bağlantısı geçmişi değiştirilemez.')
        from accounts.validators import validate_public_website
        validate_public_website(self.url)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Teslim bağlantısı geçmişi silinemez.')


class CapstoneAcademicReview(models.Model):
    class Decision(models.TextChoices):
        APPROVED = 'APPROVED', 'Onaylandı'
        REVISION_REQUIRED = 'REVISION_REQUIRED', 'Revizyon gerekli'

    submission = models.OneToOneField(CapstoneAcademicSubmission, on_delete=models.PROTECT, related_name='review')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    feedback = models.TextField(max_length=5000, blank=True)
    reviewed_at = models.DateTimeField(editable=False)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Değerlendirme geçmişi değiştirilemez.')
        if self.decision not in self.Decision.values:
            raise ValidationError('Geçersiz değerlendirme kararı.')
        if self.decision == self.Decision.REVISION_REQUIRED and not self.feedback.strip():
            raise ValidationError('Revizyon gerekçesi zorunludur.')
        self.reviewed_at = timezone.now()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Değerlendirme geçmişi silinemez.')


class CapstoneLiteratureVersion(AcademicPrivateFile):
    capstone_project = models.ForeignKey('capstone.CapstoneProject', on_delete=models.PROTECT, related_name='literature_versions')
    checkpoint = models.ForeignKey(CapstonePlanCheckpoint, on_delete=models.PROTECT, null=True, blank=True, related_name='literature_versions')
    version = models.PositiveSmallIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['version']
        constraints = [models.UniqueConstraint(fields=['capstone_project', 'version'], name='unique_capstone_literature_version')]


class CapstoneLiteratureReview(models.Model):
    version = models.OneToOneField(CapstoneLiteratureVersion, on_delete=models.PROTECT, related_name='review')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20, choices=CapstoneAcademicReview.Decision.choices)
    feedback = models.TextField(max_length=5000)
    reviewed_at = models.DateTimeField(editable=False)

    def save(self, *args, **kwargs):
        if self.pk or not self.feedback.strip() or self.decision not in CapstoneAcademicReview.Decision.values:
            raise ValidationError('Akademik geri bildirim zorunludur ve değiştirilemez.')
        self.reviewed_at = timezone.now()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Literatür değerlendirmesi silinemez.')


class CapstoneHelpRequest(models.Model):
    capstone_project = models.ForeignKey('capstone.CapstoneProject', on_delete=models.PROTECT, related_name='help_requests')
    checkpoint = models.ForeignKey(CapstonePlanCheckpoint, on_delete=models.PROTECT, null=True, blank=True, related_name='help_requests')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)


class CapstoneHelpMessage(models.Model):
    request = models.ForeignKey(CapstoneHelpRequest, on_delete=models.PROTECT, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    content = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Yardım talebi yanıtı değiştirilemez.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Yardım talebi yanıtı silinemez.')


class CapstoneHelpAttachment(AcademicPrivateFile):
    request = models.ForeignKey(CapstoneHelpRequest, on_delete=models.PROTECT, related_name='attachments')


class CapstoneMeetingRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', 'Talep edildi'
        SCHEDULED = 'SCHEDULED', 'Planlandı'
        HELD = 'HELD', 'Gerçekleşti'
        CANCELLED = 'CANCELLED', 'İptal edildi'

    capstone_project = models.ForeignKey('capstone.CapstoneProject', on_delete=models.PROTECT, related_name='meetings')
    checkpoint = models.ForeignKey(CapstonePlanCheckpoint, on_delete=models.PROTECT, null=True, blank=True, related_name='meeting_requests')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    availability_note = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CapstoneMeetingNote(models.Model):
    meeting = models.OneToOneField(CapstoneMeetingRequest, on_delete=models.PROTECT, related_name='note')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    content = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Görüşme notu değiştirilemez.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Görüşme notu silinemez.')


class CapstoneAdvisorPrivateNote(models.Model):
    capstone_project = models.ForeignKey('capstone.CapstoneProject', on_delete=models.PROTECT, related_name='private_advisor_notes')
    advisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    content = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Özel danışman notu geçmişi değiştirilemez.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Özel danışman notu silinemez.')


class CapstonePlanTemplate(models.Model):
    advisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='capstone_plan_templates')
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)


class CapstoneTemplateCheckpoint(models.Model):
    template = models.ForeignKey(CapstonePlanTemplate, on_delete=models.PROTECT, related_name='definitions')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['order']
        constraints = [models.UniqueConstraint(fields=['template', 'order'], name='unique_capstone_template_order')]


class CapstoneTemplateExpectation(models.Model):
    checkpoint = models.ForeignKey(CapstoneTemplateCheckpoint, on_delete=models.PROTECT, related_name='expectations')
    title = models.CharField(max_length=300)
    order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['order']
