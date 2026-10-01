"""Shared course assignment definitions and individual/team participation."""

import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q
from django.utils import timezone

from accounts.policies import is_teacher
from .course_requirements import default_requirements, validate_requirements


def invitation_token():
    return secrets.token_urlsafe(32)


class CourseProjectAssignment(models.Model):
    class Mode(models.TextChoices):
        INDIVIDUAL = 'INDIVIDUAL', 'Bireysel'
        GROUP = 'GROUP', 'Grup'

    course = models.ForeignKey('projects.Course', on_delete=models.PROTECT, related_name='project_assignments')
    instructor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='course_project_assignments')
    topic = models.CharField(max_length=200, blank=True)
    purpose = models.TextField(blank=True)
    expectations = models.TextField(blank=True)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.INDIVIDUAL)
    min_team_size = models.PositiveSmallIntegerField(null=True, blank=True)
    max_team_size = models.PositiveSmallIntegerField(null=True, blank=True)
    join_deadline = models.DateTimeField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    repository_required = models.BooleanField(default=False)
    creation_token = models.UUIDField(default=uuid.uuid4, editable=False)
    invitation_token = models.CharField(max_length=64, unique=True, default=invitation_token, editable=False)
    invitation_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='cancelled_course_assignments', editable=False)
    cancellation_reason = models.TextField(blank=True, editable=False)
    lifecycle_version = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['instructor', 'creation_token'], name='course_assignment_creation_unique')]

    def clean(self):
        from .models import CourseInstructor
        if self.pk and self.participants.exists():
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, field) != getattr(self, field) for field in
                   ('course_id', 'instructor_id', 'mode')):
                raise ValidationError('Katılım başladıktan sonra ders, akademisyen ve çalışma tipi değiştirilemez.')
            if self.mode == self.Mode.GROUP and self.min_team_size and self.max_team_size:
                for team in self.teams.annotate(member_count=Count('participants')):
                    size = team.member_count
                    if size > self.max_team_size or (
                        old.min_team_size != self.min_team_size and size and size < self.min_team_size
                    ):
                        raise ValidationError('Ekip büyüklüğü mevcut ekiplerı geçersiz hale getiremez.')
        if not any((self.topic.strip(), self.purpose.strip(), self.expectations.strip())):
            raise ValidationError('Proje konusu, amacı veya beklentilerinden en az birini doldurun.')
        if self.course_id and self.course.code.replace(' ', '').upper() in {'BST401', 'BST402'}:
            raise ValidationError('Bitirme Projesi dersleri özel çalışma alanından yönetilir.')
        if not self.pk and self.course_id and not self.course.is_active:
            raise ValidationError('Pasif ders için yeni çalışma oluşturulamaz.')
        if self.instructor_id and self.course_id and not (
            self.instructor.is_active and is_teacher(self.instructor)
            and CourseInstructor.objects.filter(course_id=self.course_id, instructor_id=self.instructor_id, is_active=True).exists()
        ):
            raise ValidationError('Yalnızca aktif olarak verdiğiniz ders için çalışma oluşturabilirsiniz.')
        if self.mode == self.Mode.GROUP:
            if not self.min_team_size or not self.max_team_size or not (2 <= self.min_team_size <= self.max_team_size <= 12):
                raise ValidationError('Grup büyüklüğü en az 2, en fazla 12 olmalıdır.')
        elif self.min_team_size is not None or self.max_team_size is not None:
            raise ValidationError('Bireysel çalışmada ekip büyüklüğü kullanılamaz.')
        if any(timezone.is_naive(value) for value in (
            self.join_deadline, self.starts_at, self.ends_at) if value is not None):
            raise ValidationError('Tarih ve saat bilgileri zaman dilimiyle kaydedilmelidir.')
        if self.join_deadline and self.starts_at and self.ends_at and not (
            self.join_deadline <= self.starts_at < self.ends_at
        ):
            raise ValidationError('Katılım, başlangıç ve bitiş tarihlerini sırasıyla belirleyin.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.course.code} · {self.topic or self.purpose[:50] or "Ders Projesi Çalışması"}'

    @property
    def is_cancelled(self):
        # Last cancellation details remain available after admin reactivation.
        return not self.is_active and self.cancelled_at is not None


class CourseProjectTeam(models.Model):
    assignment = models.ForeignKey(CourseProjectAssignment, on_delete=models.PROTECT, related_name='teams')
    name = models.CharField(max_length=140)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment', 'name'], name='unique_course_project_team_name')]

    def clean(self):
        if self.assignment_id and self.assignment.mode != CourseProjectAssignment.Mode.GROUP:
            raise ValidationError('Bireysel çalışmada ekip oluşturulamaz.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CourseProjectParticipation(models.Model):
    assignment = models.ForeignKey(CourseProjectAssignment, on_delete=models.PROTECT, related_name='participants')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='course_project_participations')
    team = models.ForeignKey(CourseProjectTeam, on_delete=models.PROTECT, null=True, blank=True, related_name='participants')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment', 'student'], name='unique_course_project_participation')]

    def clean(self):
        if self.team_id and self.team.assignment_id != self.assignment_id:
            raise ValidationError('Ekip farklı bir ders projesi çalışmasına ait.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CourseProjectWork(models.Model):
    assignment = models.ForeignKey(CourseProjectAssignment, on_delete=models.PROTECT, related_name='works')
    project = models.OneToOneField('projects.Project', on_delete=models.CASCADE, related_name='course_project_work')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    team = models.OneToOneField(CourseProjectTeam, on_delete=models.PROTECT, null=True, blank=True, related_name='work')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(Q(owner__isnull=False, team__isnull=True) | Q(owner__isnull=True, team__isnull=False)),
                name='course_work_owner_xor_team'),
            models.UniqueConstraint(fields=['assignment', 'owner'], condition=Q(owner__isnull=False),
                name='unique_individual_course_work'),
        ]

    def clean(self):
        if (self.owner_id is None) == (self.team_id is None):
            raise ValidationError('Çalışma bir öğrenciye veya ekibe ait olmalıdır.')
        if self.team_id and self.team.assignment_id != self.assignment_id:
            raise ValidationError('Ekip bu çalışmaya ait değil.')
        if self.project_id and self.project.course_id != self.assignment.course_id:
            raise ValidationError('Proje farklı bir derse ait.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CourseAssignmentCheckpoint(models.Model):
    assignment = models.ForeignKey(CourseProjectAssignment, on_delete=models.PROTECT, related_name='checkpoints')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField()
    due_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    evidence_requirements = models.JSONField(default=default_requirements, validators=[validate_requirements])
    scoring_enabled = models.BooleanField(default=False)
    max_points = models.PositiveSmallIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['assignment', 'order'], name='unique_course_assignment_checkpoint_order')]

    def clean(self):
        validate_requirements(self.evidence_requirements)
        if not 1 <= self.max_points <= 32767:
            raise ValidationError('Azami puan 1–32767 arasında olmalıdır.')

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if old.project_progress.exists() and (old.assignment_id != self.assignment_id or old.order != self.order):
                raise ValidationError('Projeler başladıktan sonra kontrol noktasının çalışması veya sırası değiştirilemez.')
            if old.project_progress.filter(submissions__isnull=False).exists() and any(
                getattr(old, field) != getattr(self, field) for field in ('title', 'description', 'order', 'assignment_id')
            ):
                raise ValidationError('Teslim geçmişi başladıktan sonra akademik tanım değiştirilemez.')
        return super().save(*args, **kwargs)


class CourseAssignmentExpectation(models.Model):
    checkpoint = models.ForeignKey(CourseAssignmentCheckpoint, on_delete=models.PROTECT, related_name='expected_items')
    title = models.CharField(max_length=300)
    order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['checkpoint', 'order'], name='unique_course_assignment_expectation_order')]


class CourseProjectTemplate(models.Model):
    """Teacher-owned plan snapshot, with no calendar or student records."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='course_project_templates')
    name = models.CharField(max_length=200)
    topic = models.CharField(max_length=200, blank=True)
    purpose = models.TextField(blank=True)
    expectations = models.TextField(blank=True)
    mode = models.CharField(max_length=10, choices=CourseProjectAssignment.Mode.choices, default='INDIVIDUAL')
    min_team_size = models.PositiveSmallIntegerField(null=True, blank=True)
    max_team_size = models.PositiveSmallIntegerField(null=True, blank=True)
    repository_required = models.BooleanField(default=False)
    plan = models.JSONField(default=list, blank=True)
    is_archived = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        from .course_template_services import validate_template_plan
        validate_template_plan(self.plan)
        if not any((self.topic.strip(), self.purpose.strip(), self.expectations.strip())):
            raise ValidationError('Konu, amaç veya beklenti gerekli.')
        if self.mode == 'GROUP':
            if not self.min_team_size or not self.max_team_size or not 2 <= self.min_team_size <= self.max_team_size <= 12:
                raise ValidationError('Ekip büyüklüğü 2–12 arasında olmalıdır.')
        elif self.min_team_size is not None or self.max_team_size is not None:
            raise ValidationError('Bireysel şablonda ekip büyüklüğü kullanılmaz.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CoursePrivateEvaluation(models.Model):
    """Append-only private annotations; never included in student review projections."""
    review = models.ForeignKey('projects.ProjectMilestoneReview', on_delete=models.PROTECT, related_name='private_evaluations')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.TextField(blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    max_points = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        constraints = [models.CheckConstraint(condition=Q(score__isnull=True) | Q(score__gte=0, score__lte=models.F('max_points')), name='course_private_score_bounds')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Özel değerlendirme geçmişi değiştirilemez.')
        from .course_work_services import can_manage_assignment
        checkpoint = self.review.submission.milestone.assignment_checkpoint
        if not checkpoint or not can_manage_assignment(self.actor, checkpoint.assignment):
            raise ValidationError('Özel değerlendirme yetkisi yok.')
        if self.score is not None and (not checkpoint.scoring_enabled or not 0 <= self.score <= checkpoint.max_points):
            raise ValidationError('Puanlama kapalı veya puan sınır dışında.')
        self.max_points = checkpoint.max_points if checkpoint.scoring_enabled else None
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Özel değerlendirme geçmişi silinemez.')
