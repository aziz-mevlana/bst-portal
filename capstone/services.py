from datetime import timedelta
import logging

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.urls import reverse

from accounts.policies import role_of
from core.audit import record_audit_event
from core.notifications import create_notification
from projects.models import Project, ProjectType, validate_project_upload_size

from .models import (
    CapstoneCheckpoint,
    CapstoneCheckpointEvaluation,
    CapstoneEnrollment,
    CapstoneProposal,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneSubmissionReview,
    CapstoneTask,
    CapstoneTerm,
)
from .policies import can_review_capstone, can_review_capstone_proposal, can_submit_capstone, is_capstone_eligible_student
from .workflow import TaskWorkflowState, capstone_overview, get_task_workflow_state


logger = logging.getLogger(__name__)


def _notify(recipient, actor, message, url, key):
    create_notification(recipient=recipient, actor=actor, notification_type='project_update',
                        message=message, target_url=url, dedupe_key=key)


@transaction.atomic
def submit_capstone_proposal(*, student, advisor, title, description='', term=None):
    term = term or CapstoneTerm.objects.filter(is_active=True).first()
    if term is None or not term.is_active or not is_capstone_eligible_student(student, term):
        raise ValidationError('Aktif döneme kayıtlı 4. sınıf öğrenci gereklidir.')
    enrollment = CapstoneEnrollment.objects.select_for_update().filter(term=term, student=student, is_active=True).first()
    if enrollment is None:
        raise ValidationError('Aktif dönem kaydı bulunamadı.')
    if CapstoneProposal.objects.filter(term=term, student=student, status=CapstoneProposal.Status.PENDING).exists():
        raise ValidationError('Zaten danışman onayı bekleyen bir teklifiniz var.')
    if CapstoneProject.objects.filter(project__created_by=student).exclude(
        project__development_status__in=['cancelled', 'completed']
    ).exists():
        raise ValidationError('Zaten aktif bir bitirme projeniz var.')
    try:
        proposal = CapstoneProposal.objects.create(term=term, student=student, requested_advisor=advisor,
                                                   title=title, description=description)
    except IntegrityError as exc:
        raise ValidationError('Zaten danışman onayı bekleyen bir teklifiniz var.') from exc
    record_audit_event(actor=student, action='capstone.proposal_submitted', target=proposal,
                       metadata={'term_id': term.pk, 'advisor_id': advisor.pk})
    _notify(advisor, student, f'{student.get_full_name() or student.username} bitirme projesi teklifi gönderdi.',
            reverse('capstone:advisor_home') + f'#proposal-{proposal.pk}', f'capstone-proposal-{proposal.pk}')
    return proposal


@transaction.atomic
def approve_capstone_proposal(*, proposal, actor):
    proposal = CapstoneProposal.objects.select_for_update().select_related('term', 'student', 'requested_advisor').get(pk=proposal.pk)
    if not can_review_capstone_proposal(actor, proposal):
        raise ValidationError('Bu teklifi onaylama yetkiniz yok.')
    if proposal.status != CapstoneProposal.Status.PENDING:
        raise ValidationError('Bu teklif artık beklemede değil.')
    if not proposal.requested_advisor.is_active or role_of(proposal.requested_advisor) != 'teacher':
        raise ValidationError('Seçilen danışman artık aktif akademisyen değil.')
    capstone_project = create_capstone_project(student=proposal.student, advisor=proposal.requested_advisor,
                                                title=proposal.title, description=proposal.description, term=proposal.term)
    project = capstone_project.project
    project.approval_status = 'approved'
    project.status = 'approved'
    project.save(update_fields=['approval_status', 'status'])
    proposal.status = CapstoneProposal.Status.APPROVED
    proposal.resulting_capstone_project = capstone_project
    proposal.reviewed_by = actor
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=['status', 'resulting_capstone_project', 'reviewed_by', 'reviewed_at', 'updated_at'])
    record_audit_event(actor=actor, action='capstone.proposal_approved', target=proposal,
                       metadata={'term_id': proposal.term_id, 'capstone_project_id': capstone_project.pk})
    _notify(proposal.student, actor, 'Bitirme projesi teklifiniz danışman tarafından onaylandı.',
            reverse('capstone:student_home'), f'capstone-proposal-approved-{proposal.pk}')
    return capstone_project


@transaction.atomic
def reject_capstone_proposal(*, proposal, actor, note):
    proposal = CapstoneProposal.objects.select_for_update().get(pk=proposal.pk)
    if not can_review_capstone_proposal(actor, proposal):
        raise ValidationError('Bu teklifi değerlendirme yetkiniz yok.')
    if proposal.status != CapstoneProposal.Status.PENDING:
        raise ValidationError('Bu teklif artık beklemede değil.')
    proposal.status = CapstoneProposal.Status.REJECTED
    proposal.advisor_note = (note or '').strip()
    proposal.reviewed_by = actor
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=['status', 'advisor_note', 'reviewed_by', 'reviewed_at', 'updated_at'])
    record_audit_event(actor=actor, action='capstone.proposal_rejected', target=proposal,
                       metadata={'term_id': proposal.term_id})
    _notify(proposal.student, actor, 'Bitirme projesi teklifiniz için danışman geri bildirimi var.',
            reverse('capstone:student_home'), f'capstone-proposal-rejected-{proposal.pk}')
    return proposal


@transaction.atomic
def withdraw_capstone_proposal(*, proposal, student):
    proposal = CapstoneProposal.objects.select_for_update().get(pk=proposal.pk)
    if proposal.student_id != student.pk or proposal.status != CapstoneProposal.Status.PENDING:
        raise ValidationError('Bu teklif geri çekilemez.')
    proposal.status = CapstoneProposal.Status.WITHDRAWN
    proposal.save(update_fields=['status', 'updated_at'])
    record_audit_event(actor=student, action='capstone.proposal_withdrawn', target=proposal,
                       metadata={'term_id': proposal.term_id})
    return proposal


@transaction.atomic
def create_capstone_task(*, checkpoint, actor, values):
    checkpoint = CapstoneCheckpoint.objects.select_for_update().select_related('capstone_project__project').get(pk=checkpoint.pk)
    if not can_review_capstone(actor, checkpoint.capstone_project):
        raise ValidationError('Görev oluşturma yetkiniz yok.')
    if CapstoneCheckpointEvaluation.objects.filter(checkpoint=checkpoint).exists():
        raise ValidationError('Puanlanmış değerlendirme aşamasına görev eklenemez.')
    from .workflow import CheckpointProgress, get_checkpoint_progress
    if get_checkpoint_progress(checkpoint) == CheckpointProgress.COMPLETED:
        raise ValidationError('Tamamlanmış değerlendirme aşamasına görev eklenemez.')
    task = CapstoneTask.objects.create(capstone_project=checkpoint.capstone_project, checkpoint=checkpoint,
                                      created_by=actor, **values)
    project = checkpoint.capstone_project.project
    if project.development_status == 'idea':
        project.development_status = 'planning'
        project.save(update_fields=['development_status'])
    record_audit_event(actor=actor, action='capstone.task_created', target=task,
                       metadata={'capstone_project_id': checkpoint.capstone_project_id, 'checkpoint_id': checkpoint.pk})
    _notify(checkpoint.capstone_project.project.created_by, actor, 'Bitirme projenize yeni görev eklendi.',
            reverse('capstone:student_home') + f'#task-{task.pk}', f'capstone-task-{task.pk}')
    return task


@transaction.atomic
def evaluate_capstone_checkpoint(*, checkpoint, actor, score, feedback):
    checkpoint = CapstoneCheckpoint.objects.select_for_update().select_related('capstone_project__project').get(pk=checkpoint.pk)
    if not can_review_capstone(actor, checkpoint.capstone_project):
        raise ValidationError('Bu değerlendirme aşamasını puanlama yetkiniz yok.')
    if CapstoneCheckpointEvaluation.objects.filter(checkpoint=checkpoint).exists():
        raise ValidationError('Değerlendirme aşaması zaten puanlandı.')
    evaluation = CapstoneCheckpointEvaluation.objects.create(checkpoint=checkpoint, evaluated_by=actor,
                                                              score=score, feedback=feedback)
    if checkpoint.kind == CapstoneCheckpoint.Kind.FIRST_REVIEW:
        project = checkpoint.capstone_project.project
        if project.development_status in {'idea', 'planning'}:
            project.development_status = 'in_progress'
            project.status = 'in_progress'
            project.save(update_fields=['development_status', 'status'])
    record_audit_event(actor=actor, action='capstone.checkpoint_evaluated', target=evaluation,
                       metadata={'capstone_project_id': checkpoint.capstone_project_id, 'checkpoint_id': checkpoint.pk, 'score': evaluation.score})
    _notify(checkpoint.capstone_project.project.created_by, actor, 'Bitirme projenizin değerlendirme aşaması puanlandı.',
            reverse('capstone:student_home') + f'#checkpoint-{checkpoint.pk}', f'capstone-evaluation-{evaluation.pk}')
    return evaluation


@transaction.atomic
def complete_capstone_project(*, capstone_project, actor):
    capstone_project = CapstoneProject.objects.select_for_update().select_related('project').get(pk=capstone_project.pk)
    if not can_review_capstone(actor, capstone_project):
        raise ValidationError('Projeyi tamamlama yetkiniz yok.')
    if capstone_project.completed_at:
        return capstone_project
    overview = capstone_overview(capstone_project)
    if not overview['completion_ready']:
        raise ValidationError('Tüm resmi kontrol noktaları, görev kabulleri ve akademik puanlamalar tamamlanmalıdır.')
    capstone_project.completed_at = timezone.now()
    capstone_project.completed_by = actor
    capstone_project.save(update_fields=['completed_at', 'completed_by', 'updated_at'])
    project = capstone_project.project
    project.status = 'completed'
    project.development_status = 'completed'
    project.save(update_fields=['status', 'development_status'])
    record_audit_event(actor=actor, action='capstone.project_completed', target=capstone_project,
                       metadata={'project_id': project.pk, 'term_id': capstone_project.term_id})
    _notify(project.created_by, actor, 'Bitirme projeniz akademik olarak tamamlandı. Proje vitrininizi tamamlayabilirsiniz.',
            reverse('capstone:student_home'), f'capstone-completed-{capstone_project.pk}')
    return capstone_project


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
    duplicate_exists = duplicate_exists or CapstoneProject.objects.filter(
        project__created_by=student
    ).exclude(project__development_status__in=['cancelled', 'completed']).exists()
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
            record_audit_event(actor=student, action='capstone.submission_created', target=attempt,
                               metadata={'task_id': locked_task.pk, 'attempt_number': attempt.attempt_number})
            _notify(locked_task.capstone_project.project.advisor, student, 'Bitirme projesinde yeni teslim değerlendirme bekliyor.',
                    reverse('capstone:advisor_project_detail', args=[locked_task.capstone_project_id]) + f'#task-{locked_task.pk}',
                    f'capstone-submission-{attempt.pk}')
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

            review = CapstoneSubmissionReview.objects.create(
                submission_attempt=locked_attempt,
                reviewed_by=reviewer,
                decision=decision,
                feedback=feedback,
            )
            record_audit_event(actor=reviewer, action='capstone.submission_reviewed', target=review,
                               metadata={'task_id': locked_task.pk, 'attempt_id': locked_attempt.pk, 'decision': decision})
            _notify(capstone_project.project.created_by, reviewer, 'Bitirme projesi tesliminiz değerlendirildi.',
                    reverse('capstone:student_home') + f'#task-{locked_task.pk}', f'capstone-review-{review.pk}')
            return review
    except IntegrityError as exc:
        raise ValidationError('Bu teslim denemesi daha önce değerlendirilmiş.') from exc
