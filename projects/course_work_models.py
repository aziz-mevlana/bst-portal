"""Shared course assignment definitions and individual/team participation."""

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.policies import is_teacher


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
    invitation_token = models.CharField(max_length=64, unique=True, default=invitation_token, editable=False)
    invitation_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        from .models import CourseInstructor
        if self.pk and self.participants.exists():
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, field) != getattr(self, field) for field in
                   ('course_id', 'instructor_id', 'mode', 'min_team_size', 'max_team_size')):
                raise ValidationError('Katılım başladıktan sonra ders, akademisyen ve takım yapısı değiştirilemez.')
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
            raise ValidationError('Bireysel çalışmada takım büyüklüğü kullanılamaz.')
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


class CourseProjectTeam(models.Model):
    assignment = models.ForeignKey(CourseProjectAssignment, on_delete=models.PROTECT, related_name='teams')
    name = models.CharField(max_length=140)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment', 'name'], name='unique_course_project_team_name')]

    def clean(self):
        if self.assignment_id and self.assignment.mode != CourseProjectAssignment.Mode.GROUP:
            raise ValidationError('Bireysel çalışmada takım oluşturulamaz.')

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
            raise ValidationError('Takım farklı bir ders projesi çalışmasına ait.')

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
            raise ValidationError('Çalışma bir öğrenciye veya takıma ait olmalıdır.')
        if self.team_id and self.team.assignment_id != self.assignment_id:
            raise ValidationError('Takım bu çalışmaya ait değil.')
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['assignment', 'order'], name='unique_course_assignment_checkpoint_order')]

    def save(self, *args, **kwargs):
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
