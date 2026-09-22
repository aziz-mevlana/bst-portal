from datetime import timedelta
import logging

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Max

from accounts.policies import role_of
from core.audit import record_audit_event
from projects.models import Project, ProjectType, validate_project_upload_size

from .models import (
    CapstoneCheckpoint,
    CapstoneEnrollment,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneSubmissionReview,
    CapstoneTask,
    CapstoneTerm,
)
from .policies import can_review_capstone, can_submit_capstone, is_capstone_eligible_student
from .workflow import TaskWorkflowState, get_task_workflow_state


logger = logging.getLogger(__name__)


@transaction.atomic
def create_capstone_checkpoints(capstone_project):
    """Create the four official checkpoints and return them in academic order."""

    term = capstone_project.term
    schedule = (
        (CapstoneCheckpoint.Kind.FIRST_REVIEW, term.starts_at + timedelta(weeks=4)),
        (CapstoneCheckpoint.Kind.MIDTERM_REVIEW, term.midterm_at),
        (CapstoneCheckpoint.Kind.POST_MIDTERM_REVIEW, term.midterm_at + timedelta(weeks=4)),
        (CapstoneCheckpoint.Kind.FINAL_REVIEW, term.final_at),
    )

    if schedule[0][1] > term.midterm_at:
        raise ValidationError('İlk değerlendirme tarihi ara değerlendirme tarihinden sonra olamaz.')
    if schedule[2][1] > term.final_at:
        raise ValidationError('Ara değerlendirme sonrası kontrol final tarihinden sonra olamaz.')

    checkpoints = []
    for kind, due_at in schedule:
        checkpoint, _ = CapstoneCheckpoint.objects.get_or_create(
            capstone_project=capstone_project,
            kind=kind,
            defaults={'due_at': due_at},
        )
        checkpoints.append(checkpoint)
    return checkpoints


@transaction.atomic
def create_capstone_project(*, student, advisor, title, description='', term=None):
    """Create a complete CAPSTONE project aggregate for one enrolled student."""

    if term is None:
        term = CapstoneTerm.objects.select_for_update().filter(is_active=True).first()
        if term is None:
            raise ValidationError('Aktif bir bitirme projesi dönemi bulunamadı.')
    else:
        if term.pk is None:
            raise ValidationError('Geçerli bir bitirme projesi dönemi seçilmelidir.')
        term = CapstoneTerm.objects.select_for_update().filter(pk=term.pk).first()
        if term is None:
            raise ValidationError('Bitirme projesi dönemi bulunamadı.')

    if not term.is_active:
        raise ValidationError('Pasif bir dönemde bitirme projesi başlatılamaz.')
    if not is_capstone_eligible_student(student, term):
        raise ValidationError('Öğrenci bu dönem için bitirme projesi başlatmaya uygun değil.')

    enrollment = CapstoneEnrollment.objects.select_for_update().filter(
        term=term,
        student=student,
        is_active=True,
    ).first()
    if enrollment is None:
        raise ValidationError('Öğrencinin bu dönem için aktif kaydı bulunamadı.')

    if (
        advisor is None
        or not getattr(advisor, 'is_authenticated', False)
        or not advisor.is_active
        or advisor.is_staff
        or advisor.is_superuser
        or role_of(advisor) != 'teacher'
    ):
        raise ValidationError({'advisor': 'Danışman aktif bir akademisyen olmalıdır.'})

    project_type = ProjectType.objects.filter(code='CAPSTONE').first()
    if project_type is None:
        raise ValidationError('CAPSTONE proje tipi bulunamadı.')
    if not project_type.is_active:
        raise ValidationError('CAPSTONE proje tipi aktif değil.')

    duplicate_exists = CapstoneProject.objects.filter(
        term=term,
        project__created_by=student,
    ).exclude(project__development_status='cancelled').exists()
    if duplicate_exists:
        raise ValidationError('Öğrencinin bu dönem için zaten bir bitirme projesi bulunuyor.')

    requires_approval = project_type.requires_approval
    project = Project(
        title=title,
        description=description,
        created_by=student,
        advisor=advisor,
        project_type=project_type,
        visibility='private',
        is_private=True,
        status='in_review' if requires_approval else 'approved',
        approval_status='pending' if requires_approval else 'approved',
        development_status='idea',
    )
    project.full_clean()
    project.save()
    project.team.add(student)

    capstone_project = CapstoneProject.objects.create(project=project, term=term)
    create_capstone_checkpoints(capstone_project)
    record_audit_event(
        actor=student,
        action='capstone.project_created',
        target=project,
    )
    return capstone_project


def _validate_submission_upload(upload):
    if not isinstance(upload, UploadedFile) or not upload.name:
        raise ValidationError('Geçerli bir yüklenmiş dosya sağlanmalıdır.')
    if upload.size <= 0:
        raise ValidationError('Boş dosya teslim edilemez.')
    validate_project_upload_size(upload)


def _cleanup_submission_files(saved_files):
    for storage, name in reversed(saved_files):
        try:
            storage.delete(name)
        except Exception:
            logger.exception('CAPSTONE teslim rollback dosya temizliği başarısız oldu.')


def create_capstone_submission(*, task, student, files):
    """Create one immutable submission attempt with its complete private file set."""

    if task is None or getattr(task, 'pk', None) is None:
        raise ValidationError({'task': 'Geçerli bir bitirme projesi görevi seçilmelidir.'})

    try:
        submitted_files = tuple(files or ())
    except TypeError as exc:
        raise ValidationError({'files': 'Teslim dosyaları geçerli bir liste olmalıdır.'}) from exc

    saved_files = []
    try:
        with transaction.atomic():
            try:
                locked_task = CapstoneTask.objects.select_for_update().get(pk=task.pk)
            except CapstoneTask.DoesNotExist as exc:
                raise ValidationError({'task': 'Bitirme projesi görevi bulunamadı.'}) from exc

            if not can_submit_capstone(student, locked_task.capstone_project):
                raise ValidationError(
                    {'student': 'Teslimi yalnızca bitirme projesinin sahibi aktif öğrenci yapabilir.'}
                )

            workflow_state = get_task_workflow_state(locked_task)
            if workflow_state == TaskWorkflowState.AWAITING_REVIEW:
                raise ValidationError('Önceki teslim henüz değerlendirilmedi.')
            if workflow_state == TaskWorkflowState.ACCEPTED:
                raise ValidationError('Kabul edilmiş görev için yeni teslim oluşturulamaz.')

            if len(submitted_files) != locked_task.required_file_count:
                raise ValidationError({
                    'files': (
                        f'Bu görev için tam olarak {locked_task.required_file_count} dosya '
                        'teslim edilmelidir.'
                    ),
                })
            for upload in submitted_files:
                _validate_submission_upload(upload)

            last_attempt_number = (
                CapstoneSubmissionAttempt.objects.filter(task=locked_task)
                .aggregate(number=Max('attempt_number'))['number']
                or 0
            )
            attempt = CapstoneSubmissionAttempt.objects.create(
                task=locked_task,
                submitted_by=student,
                attempt_number=last_attempt_number + 1,
            )

            for upload in submitted_files:
                submission_file = CapstoneSubmissionFile(
                    submission_attempt=attempt,
                    file=upload,
                )
                try:
                    submission_file.save()
                finally:
                    if submission_file.file and submission_file.file._committed:
                        saved_files.append(
                            (submission_file.file.storage, submission_file.file.name)
                        )

            return attempt
    except IntegrityError as exc:
        _cleanup_submission_files(saved_files)
        raise ValidationError(
            'Teslim numarası eşzamanlı başka bir işlem tarafından kullanıldı; tekrar deneyin.'
        ) from exc
    except Exception:
        _cleanup_submission_files(saved_files)
        raise


def review_capstone_submission(*, submission_attempt, reviewer, decision, feedback):
    """Create the one immutable academic review allowed for a submission attempt."""

    if submission_attempt is None or getattr(submission_attempt, 'pk', None) is None:
        raise ValidationError(
            {'submission_attempt': 'Geçerli bir teslim denemesi seçilmelidir.'}
        )

    try:
        with transaction.atomic():
            attempt_reference = CapstoneSubmissionAttempt.objects.filter(
                pk=submission_attempt.pk,
            ).values('task_id').first()
            if attempt_reference is None:
                raise ValidationError(
                    {'submission_attempt': 'Teslim denemesi bulunamadı.'}
                )

            try:
                locked_task = CapstoneTask.objects.select_for_update().get(
                    pk=attempt_reference['task_id'],
                )
            except CapstoneTask.DoesNotExist as exc:
                raise ValidationError(
                    {'submission_attempt': 'Teslimin bağlı olduğu görev bulunamadı.'}
                ) from exc

            try:
                locked_attempt = CapstoneSubmissionAttempt.objects.select_for_update().get(
                    pk=submission_attempt.pk,
                    task=locked_task,
                )
            except CapstoneSubmissionAttempt.DoesNotExist as exc:
                raise ValidationError(
                    {'submission_attempt': 'Teslim denemesi bulunamadı.'}
                ) from exc

            latest_attempt_id = (
                CapstoneSubmissionAttempt.objects.filter(task=locked_task)
                .order_by('-attempt_number', '-pk')
                .values_list('pk', flat=True)
                .first()
            )
            if latest_attempt_id != locked_attempt.pk:
                raise ValidationError('Yalnızca görevin en güncel teslimi değerlendirilebilir.')

            capstone_project = locked_attempt.task.capstone_project
            if not can_review_capstone(reviewer, capstone_project):
                raise ValidationError(
                    {'reviewer': 'Bu teslimi değerlendirme yetkiniz bulunmuyor.'}
                )

            if CapstoneSubmissionReview.objects.filter(
                submission_attempt=locked_attempt,
            ).exists():
                raise ValidationError('Bu teslim denemesi daha önce değerlendirilmiş.')

            return CapstoneSubmissionReview.objects.create(
                submission_attempt=locked_attempt,
                reviewed_by=reviewer,
                decision=decision,
                feedback=feedback,
            )
    except IntegrityError as exc:
        raise ValidationError('Bu teslim denemesi daha önce değerlendirilmiş.') from exc
