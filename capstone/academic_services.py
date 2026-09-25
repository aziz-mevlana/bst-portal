"""CAPSTONE V3 operations; V2 academic records stay read-only and untouched."""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from accounts.policies import is_admin, role_of
from accounts.validators import validate_public_website
from core.audit import record_audit_event
from core.notifications import create_notification
from projects.models import detect_project_upload_type, validate_project_upload_content, validate_project_upload_size

from .academic_models import (
    CapstoneAcademicReview, CapstoneAcademicSubmission, CapstoneAcademicSubmissionFile,
    CapstoneAcademicSubmissionLink, CapstoneAdvisorPrivateNote, CapstoneChecklistItem,
    CapstoneChecklistTick, CapstoneHelpAttachment, CapstoneHelpMessage, CapstoneHelpRequest,
    CapstoneLiteratureReview, CapstoneLiteratureVersion, CapstoneMeetingNote,
    CapstoneMeetingRequest, CapstonePlan, CapstonePlanCheckpoint, CapstonePlanTemplate,
    CapstoneStudentCheckpoint, CapstoneTemplateCheckpoint, CapstoneTemplateExpectation,
)
from .models import CapstoneEnrollment, CapstoneProject, CapstoneTerm
from .policies import can_review_capstone, can_submit_capstone, is_capstone_eligible_student
from .services import create_capstone_project


logger = logging.getLogger(__name__)


def _teacher(user):
    return bool(user and user.is_authenticated and user.is_active and role_of(user) == 'teacher'
                and not user.is_staff and not user.is_superuser)


def _notice(recipient, actor, message, key, url=None, title=''):
    create_notification(recipient=recipient, actor=actor, notification_type='project_update',
                        message=message, title=title, target_url=url or reverse('capstone:student_home'), dedupe_key=key)


def _audit(actor, action, target, **metadata):
    record_audit_event(actor=actor, action=action, target=target, metadata=metadata)


def _project_for(enrollment):
    return CapstoneProject.objects.select_related('project').filter(term=enrollment.term, project__created_by=enrollment.student).exclude(
        project__development_status='cancelled'
    ).first()


def _lock_current_project(project):
    """Serialize academic writes with advisor changes and admin purges."""
    from projects.models import Project

    current = CapstoneProject.objects.select_for_update(of=('self',)).get(pk=project.pk)
    student_id = Project.objects.filter(pk=current.project_id).values_list('created_by_id', flat=True).get()
    CapstoneEnrollment.objects.select_for_update(of=('self',)).filter(
        term_id=current.term_id, student_id=student_id,
    ).first()
    current.project = Project.objects.select_for_update().get(pk=current.project_id)
    return current


@transaction.atomic
def enroll_student(*, term, student, actor):
    if not is_admin(actor) or not term.is_active or not student.is_active or role_of(student) not in {'student', 'staff_student'} or getattr(student.profile, 'class_level', None) != '4':
        raise PermissionDenied
    enrollment, created = CapstoneEnrollment.objects.get_or_create(term=term, student=student,
        defaults={'approved_by': actor, 'is_active': True})
    if not created and not enrollment.is_active:
        enrollment.is_active = True
        enrollment.save(update_fields=['is_active', 'updated_at'])
    if created:
        _audit(actor, 'capstone.enrollment_created', enrollment, term_id=term.pk, student_id=student.pk)
    return enrollment


@transaction.atomic
def claim_student(*, enrollment, advisor):
    if not _teacher(advisor):
        raise PermissionDenied
    enrollment = CapstoneEnrollment.objects.select_for_update(of=('self',)).select_related('term', 'student', 'student__profile').get(pk=enrollment.pk)
    if not enrollment.term.is_active or not enrollment.is_active or not is_capstone_eligible_student(enrollment.student, enrollment.term):
        raise ValidationError('Öğrenci aktif dönem danışmanlığına uygun değil.')
    if enrollment.advisor_id:
        if enrollment.advisor_id == advisor.pk:
            raise ValidationError('Bu öğrenci zaten danışmanlığınızda.')
        raise ValidationError('Bu öğrenci başka bir akademisyen tarafından danışmanlığa alınmış.')
    if CapstoneProject.objects.filter(project__created_by=enrollment.student).exclude(
        project__development_status__in=['cancelled', 'completed']
    ).exists():
        raise ValidationError('Öğrencinin zaten aktif bir bitirme projesi var.')
    enrollment.advisor = advisor
    enrollment.advisor_assigned_at = timezone.now()
    enrollment.advisor_assigned_by = advisor
    enrollment.save(update_fields=['advisor', 'advisor_assigned_at', 'advisor_assigned_by', 'updated_at'])
    CapstonePlan.objects.get_or_create(term=enrollment.term, advisor=advisor)
    _audit(advisor, 'capstone.advisor_assigned', enrollment, term_id=enrollment.term_id,
           student_id=enrollment.student_id, advisor_id=advisor.pk)
    _notice(enrollment.student, advisor,
            f'{advisor.get_full_name() or advisor.username} Bitirme Projesi danışmanınız olarak atandı. Proje bilgilerinizi tamamlayabilirsiniz.',
            f'capstone-advisor-assigned-{enrollment.pk}-{advisor.pk}', title='Bitirme Projesi danışmanınız atandı.')
    return enrollment


def claim_students(*, enrollment_ids, advisor):
    """Claim each enrollment independently so one concurrent claim cannot undo the batch."""
    if not _teacher(advisor):
        raise PermissionDenied
    ids = list(dict.fromkeys(enrollment_ids))
    if not ids or len(ids) > 200 or any(not str(value).isascii() or not str(value).isdigit() for value in ids):
        raise ValidationError('En fazla 200 geçerli öğrenci seçin.')
    added = 0
    skipped = 0
    for enrollment_id in sorted(map(int, ids)):
        try:
            enrollment = CapstoneEnrollment.objects.get(pk=enrollment_id)
            claim_student(enrollment=enrollment, advisor=advisor)
            added += 1
        except (CapstoneEnrollment.DoesNotExist, ValidationError):
            skipped += 1
    return added, skipped


@transaction.atomic
def unassign_student(*, enrollment, actor, reason=''):
    enrollment = CapstoneEnrollment.objects.select_for_update().select_related('term', 'student').get(pk=enrollment.pk)
    if not (is_admin(actor) or (_teacher(actor) and enrollment.advisor_id == actor.pk)):
        raise PermissionDenied
    project = _project_for(enrollment)
    if not enrollment.advisor_id or (project and not is_admin(actor)):
        raise ValidationError('Proje başladıktan sonra danışmanlık yalnızca yönetici değişiklik akışıyla düzenlenebilir.')
    if project and not (reason or '').strip():
        raise ValidationError('Aktif proje danışmanlığını kaldırmak için gerekçe zorunludur.')
    old_id = enrollment.advisor_id
    if project:
        project.project.advisor = None
        project.project.save(update_fields=['advisor'])
    enrollment.advisor = None
    enrollment.advisor_assigned_at = None
    enrollment.advisor_assigned_by = None
    enrollment.save(update_fields=['advisor', 'advisor_assigned_at', 'advisor_assigned_by', 'updated_at'])
    _audit(actor, 'capstone.advisor_unassigned', enrollment, term_id=enrollment.term_id,
           student_id=enrollment.student_id, old_advisor_id=old_id, project_id=project.pk if project else None,
           reason=(reason or '').strip())
    _notice(enrollment.student, actor, 'Bitirme Projesi danışman atamanız kaldırıldı.',
            f'capstone-advisor-unassigned-{enrollment.pk}-{timezone.now().timestamp()}')
    return enrollment


@transaction.atomic
def purge_capstone_project(*, capstone_project, actor, reason, keep_advisor):
    """Explicit admin purge. All file removals happen only after the DB commits."""
    if not is_admin(actor) or not (reason or '').strip():
        raise PermissionDenied
    from .academic_models import (
        CapstoneAcademicReview, CapstoneAcademicSubmission, CapstoneAcademicSubmissionFile,
        CapstoneAcademicSubmissionLink, CapstoneAdvisorPrivateNote, CapstoneChecklistTick,
        CapstoneHelpAttachment, CapstoneHelpMessage, CapstoneLiteratureReview,
        CapstoneMeetingNote,
    )
    from .models import (CapstoneCheckpoint, CapstoneCheckpointEvaluation, CapstoneProposal,
                         CapstoneSubmissionAttempt, CapstoneSubmissionFile, CapstoneSubmissionReview,
                         CapstoneTask)
    capstone_project = CapstoneProject.objects.select_for_update().select_related('project').get(pk=capstone_project.pk)
    project = capstone_project.project
    enrollment = CapstoneEnrollment.objects.select_for_update().filter(
        term=capstone_project.term, student_id=project.created_by_id).first()
    if project.project_type.code != 'CAPSTONE':
        raise ValidationError('Yalnız Bitirme Projesi kaydı kalıcı silinebilir.')
    snapshot = {'capstone_project_id': capstone_project.pk, 'project_id': project.pk,
                'student_id': project.created_by_id, 'title': project.title,
                'reason': reason.strip(), 'keep_advisor': keep_advisor}
    progress = list(capstone_project.academic_progress.values_list('pk', flat=True))
    submissions = CapstoneAcademicSubmission.objects.filter(progress_id__in=progress)
    files = []
    for queryset in (
        CapstoneAcademicSubmissionFile.objects.filter(submission__in=submissions),
        capstone_project.literature_versions.all(),
        CapstoneHelpAttachment.objects.filter(request__capstone_project=capstone_project),
        CapstoneSubmissionFile.objects.filter(submission_attempt__task__capstone_project=capstone_project),
    ):
        files.extend((item.file.storage, item.file.name) for item in queryset if item.file)
    files.extend((item.file.storage, item.file.name) for item in project.media.all() if item.file)
    files.extend((item.evidence_file.storage, item.evidence_file.name)
                 for item in project.achievements.all() if item.evidence_file)
    CapstoneAcademicReview.objects.filter(submission__in=submissions).delete()
    CapstoneAcademicSubmissionFile.objects.filter(submission__in=submissions).delete()
    CapstoneAcademicSubmissionLink.objects.filter(submission__in=submissions).delete()
    submissions.delete()
    CapstoneChecklistTick.objects.filter(progress_id__in=progress).delete()
    capstone_project.academic_progress.all().delete()
    CapstoneLiteratureReview.objects.filter(version__capstone_project=capstone_project).delete()
    capstone_project.literature_versions.all().delete()
    CapstoneHelpMessage.objects.filter(request__capstone_project=capstone_project).delete()
    CapstoneHelpAttachment.objects.filter(request__capstone_project=capstone_project).delete()
    capstone_project.help_requests.all().delete()
    CapstoneMeetingNote.objects.filter(meeting__capstone_project=capstone_project).delete()
    capstone_project.meetings.all().delete()
    CapstoneAdvisorPrivateNote.objects.filter(capstone_project=capstone_project).delete()
    CapstoneCheckpointEvaluation.objects.filter(checkpoint__capstone_project=capstone_project).delete()
    CapstoneSubmissionReview.objects.filter(submission_attempt__task__capstone_project=capstone_project).delete()
    CapstoneSubmissionFile.objects.filter(submission_attempt__task__capstone_project=capstone_project).delete()
    CapstoneSubmissionAttempt.objects.filter(task__capstone_project=capstone_project).delete()
    CapstoneTask.objects.filter(capstone_project=capstone_project).delete()
    CapstoneCheckpoint.objects.filter(capstone_project=capstone_project).delete()
    CapstoneProposal.objects.filter(resulting_capstone_project=capstone_project).update(resulting_capstone_project=None)
    capstone_project.delete()
    project.delete()
    if enrollment and not keep_advisor:
        enrollment.advisor = None
        enrollment.advisor_assigned_at = None
        enrollment.advisor_assigned_by = None
        enrollment.save(update_fields=['advisor', 'advisor_assigned_at', 'advisor_assigned_by', 'updated_at'])
    _audit(actor, 'capstone.project_purged', target=None, **snapshot)
    def remove_unreferenced_files():
        from projects.models import ProjectAchievement, ProjectMedia

        file_models = (
            (CapstoneAcademicSubmissionFile, 'file'),
            (CapstoneLiteratureVersion, 'file'),
            (CapstoneHelpAttachment, 'file'),
            (CapstoneSubmissionFile, 'file'),
            (ProjectMedia, 'file'),
            (ProjectAchievement, 'evidence_file'),
        )
        seen = set()
        for storage, name in files:
            if not name or (id(storage), name) in seen:
                continue
            seen.add((id(storage), name))
            try:
                if any(model.objects.filter(**{field: name}).exists() for model, field in file_models):
                    continue
                storage.delete(name)
            except Exception:
                logger.exception('Bitirme Projesi silme sonrası dosya temizlenemedi: %s', name)

    transaction.on_commit(remove_unreferenced_files)
    return snapshot


@transaction.atomic
def change_advisor(*, enrollment, new_advisor, actor, reason):
    if not is_admin(actor) or not _teacher(new_advisor) or not (reason or '').strip():
        raise PermissionDenied
    enrollment = CapstoneEnrollment.objects.select_for_update().select_related('term', 'student').get(pk=enrollment.pk)
    project = _project_for(enrollment)
    old_id = enrollment.advisor_id
    if old_id == new_advisor.pk:
        return enrollment
    enrollment.advisor = new_advisor
    enrollment.advisor_assigned_at = timezone.now()
    enrollment.advisor_assigned_by = actor
    enrollment.save(update_fields=['advisor', 'advisor_assigned_at', 'advisor_assigned_by', 'updated_at'])
    if project:
        project.project.advisor = new_advisor
        project.project.save(update_fields=['advisor'])
    CapstonePlan.objects.get_or_create(term=enrollment.term, advisor=new_advisor)
    _audit(actor, 'capstone.advisor_changed', enrollment, old_advisor_id=old_id,
           new_advisor_id=new_advisor.pk, student_id=enrollment.student_id, reason=reason.strip())
    _notice(enrollment.student, actor, 'Bitirme Projesi danışmanınız değiştirildi.',
            f'capstone-advisor-changed-{enrollment.pk}-{new_advisor.pk}')
    return enrollment


@transaction.atomic
def initialize_project(*, enrollment, student, title, description):
    enrollment = CapstoneEnrollment.objects.select_for_update(of=('self',)).select_related('term', 'student', 'advisor').get(pk=enrollment.pk)
    if student.pk != enrollment.student_id or not is_capstone_eligible_student(student, enrollment.term) or not enrollment.advisor_id:
        raise PermissionDenied
    if not _teacher(enrollment.advisor):
        raise ValidationError('Atanmış danışman artık aktif akademisyen değil.')
    if _project_for(enrollment):
        raise ValidationError('Bitirme projesi zaten oluşturulmuş.')
    project = create_capstone_project(student=student, advisor=enrollment.advisor, term=enrollment.term,
                                      title=title, description=description, create_checkpoints=False)
    base = project.project
    base.approval_status = 'approved'
    base.status = 'approved'
    base.save(update_fields=['approval_status', 'status'])
    _audit(student, 'capstone.project_initialized', project, enrollment_id=enrollment.pk)
    _notice(enrollment.advisor, student, 'Öğrenci bitirme projesi bilgilerini tamamladı.',
            f'capstone-project-initialized-{project.pk}', reverse('capstone:advisor_project_detail', args=[project.pk]))
    return project


def plan_for_project(project):
    return CapstonePlan.objects.filter(term=project.term, advisor_id=project.project.advisor_id, is_active=True).first()


@transaction.atomic
def save_plan_checkpoint(*, plan, actor, title, description, order, due_at, checkpoint=None):
    plan = CapstonePlan.objects.select_for_update().select_related('term').get(pk=plan.pk)
    if not (is_admin(actor) or (_teacher(actor) and plan.advisor_id == actor.pk)):
        raise PermissionDenied
    if checkpoint:
        checkpoint = CapstonePlanCheckpoint.objects.select_for_update().get(pk=checkpoint.pk, plan=plan)
        if not checkpoint.is_active:
            raise ValidationError('Pasif kontrol noktası düzenlenemez.')
        previous_definition = (checkpoint.title, checkpoint.description, checkpoint.order)
        if checkpoint.student_progress.filter(submissions__isnull=False).exists() and (
            checkpoint.title != title or checkpoint.description != description or checkpoint.order != order
        ):
            raise ValidationError('Teslim geçmişi başladıktan sonra kontrol noktasının akademik tanımı değiştirilemez.')
        old_due = checkpoint.due_at
        if plan.definitions.filter(order=order).exclude(pk=checkpoint.pk).exists():
            raise ValidationError('Bu sıra numarası başka bir kontrol noktasında kullanılıyor.')
        checkpoint.title, checkpoint.description, checkpoint.order, checkpoint.due_at = title, description, order, due_at
        checkpoint.save(update_fields=['title', 'description', 'order', 'due_at', 'updated_at'])
    else:
        old_due = None
        previous_definition = None
        if plan.definitions.filter(order=order).exists():
            raise ValidationError('Bu sıra numarası başka bir kontrol noktasında kullanılıyor.')
        checkpoint = CapstonePlanCheckpoint.objects.create(plan=plan, title=title, description=description,
                                                            order=order, due_at=due_at)
    _audit(actor, 'capstone.checkpoint_updated' if old_due else 'capstone.checkpoint_created', checkpoint,
           plan_id=plan.pk, term_id=plan.term_id)
    if old_due and old_due != due_at:
        _audit(actor, 'capstone.deadline_changed', checkpoint, plan_id=plan.pk,
               old_due_at=old_due.isoformat(), new_due_at=due_at.isoformat())
        for enrollment in CapstoneEnrollment.objects.filter(term=plan.term, advisor=plan.advisor, is_active=True).select_related('student'):
            _notice(enrollment.student, actor, f'{checkpoint.title} kontrol noktasının tarihi değişti.',
                    f'capstone-deadline-{checkpoint.pk}-{checkpoint.updated_at.timestamp()}')
    elif not old_due:
        for enrollment in CapstoneEnrollment.objects.filter(term=plan.term, advisor=plan.advisor, is_active=True).select_related('student'):
            _notice(enrollment.student, actor, f'Kontrol planına {checkpoint.title} eklendi.',
                    f'capstone-checkpoint-{checkpoint.pk}')
    elif previous_definition != (title, description, order):
        for enrollment in CapstoneEnrollment.objects.filter(term=plan.term, advisor=plan.advisor, is_active=True).select_related('student'):
            _notice(enrollment.student, actor, 'Bitirme Projesi kontrol planınız güncellendi.',
                    f'capstone-plan-update-{checkpoint.pk}-{checkpoint.updated_at.timestamp()}')
    return checkpoint


@transaction.atomic
def archive_checkpoint(*, checkpoint, actor):
    checkpoint = CapstonePlanCheckpoint.objects.select_for_update(of=('self',)).select_related('plan').get(pk=checkpoint.pk)
    if not (is_admin(actor) or (_teacher(actor) and checkpoint.plan.advisor_id == actor.pk)):
        raise PermissionDenied
    if not checkpoint.is_active:
        raise ValidationError('Kontrol noktası zaten pasif.')
    if checkpoint.student_progress.exists() or checkpoint.expectations.exists() or checkpoint.literature_versions.exists() or checkpoint.help_requests.exists() or checkpoint.meeting_requests.exists():
        checkpoint.is_active = False
        checkpoint.save(update_fields=['is_active', 'updated_at'])
        action = 'capstone.checkpoint_archived'
    else:
        action = 'capstone.checkpoint_deleted'
    _audit(actor, action, checkpoint, plan_id=checkpoint.plan_id)
    checkpoint_id = checkpoint.pk
    if action.endswith('deleted'):
        checkpoint.delete()
    for enrollment in CapstoneEnrollment.objects.filter(term=checkpoint.plan.term, advisor=checkpoint.plan.advisor, is_active=True).select_related('student'):
        _notice(enrollment.student, actor, 'Bitirme Projesi kontrol planınız güncellendi.',
                f'capstone-plan-archive-{checkpoint_id}-{timezone.now().timestamp()}')
    return action


@transaction.atomic
def add_expectation(*, checkpoint, actor, title, order):
    checkpoint = CapstonePlanCheckpoint.objects.select_for_update(of=('self',)).select_related('plan').get(pk=checkpoint.pk)
    if not checkpoint.is_active or not (is_admin(actor) or (_teacher(actor) and checkpoint.plan.advisor_id == actor.pk)):
        raise PermissionDenied
    if not title.strip() or order < 1:
        raise ValidationError('Beklenen başlığı ve pozitif sıra numarası gereklidir.')
    if checkpoint.expectations.filter(order=order).exists():
        raise ValidationError('Bu sıra numarası başka bir beklenen için kullanılıyor.')
    item = CapstoneChecklistItem.objects.create(checkpoint=checkpoint, title=title.strip(), order=order)
    _audit(actor, 'capstone.expectation_created', item, checkpoint_id=checkpoint.pk)
    for enrollment in CapstoneEnrollment.objects.filter(term=checkpoint.plan.term,
        advisor=checkpoint.plan.advisor, is_active=True).select_related('student'):
        _notice(enrollment.student, actor, f'{checkpoint.title} kontrol noktasının beklenenleri güncellendi.',
                f'capstone-expectation-{item.pk}')
    return item


@transaction.atomic
def _progress(project, checkpoint):
    project = _lock_current_project(project)
    checkpoint = CapstonePlanCheckpoint.objects.select_for_update(of=('self',)).select_related('plan').get(pk=checkpoint.pk)
    if not checkpoint.is_active or checkpoint.plan.term_id != project.term_id or checkpoint.plan.advisor_id != project.project.advisor_id:
        raise PermissionDenied
    progress, _ = CapstoneStudentCheckpoint.objects.get_or_create(capstone_project=project, checkpoint=checkpoint)
    return CapstoneStudentCheckpoint.objects.select_for_update().get(pk=progress.pk)


def checkpoint_state(project, checkpoint, now=None):
    progress = CapstoneStudentCheckpoint.objects.filter(capstone_project=project, checkpoint=checkpoint).first()
    return _checkpoint_state(progress, checkpoint, now=now)


def _checkpoint_state(progress, checkpoint, *, submissions=None, ticks=None, now=None):
    if progress:
        if submissions is None:
            submissions = list(progress.submissions.select_related('review').order_by('attempt_number'))
        latest = submissions[-1] if submissions else None
        if latest:
            if not hasattr(latest, 'review'):
                return 'AWAITING_REVIEW'
            return 'APPROVED' if latest.review.decision == 'APPROVED' else 'REVISION_REQUIRED'
        due = progress.due_at
        if (now or timezone.now()) > due:
            return 'OVERDUE'
        if ticks is None:
            ticks = list(progress.ticks.all())
        checked_ids = {tick.item_id for tick in ticks if tick.is_checked}
        expected_ids = {item.pk for item in checkpoint.expectations.all() if item.is_active}
        if expected_ids and expected_ids <= checked_ids:
            return 'AWAITING_SUBMISSION'
        if checked_ids:
            return 'IN_PROGRESS'
    else:
        due = checkpoint.due_at
    return 'OVERDUE' if (now or timezone.now()) > due else 'NOT_STARTED'


ACADEMIC_STATE_LABELS = {
    'NOT_STARTED': 'Başlanmadı', 'IN_PROGRESS': 'Devam Ediyor',
    'AWAITING_SUBMISSION': 'Teslim Bekleniyor',
    'AWAITING_REVIEW': 'Değerlendirme Bekliyor', 'REVISION_REQUIRED': 'Revizyon Gerekli',
    'APPROVED': 'Onaylandı', 'OVERDUE': 'Gecikti',
}


def academic_overview(project, *, preloaded=None):
    if preloaded is None:
        plan = plan_for_project(project)
        definitions = list(plan.definitions.filter(is_active=True).prefetch_related('expectations') if plan else [])
        progress_by_checkpoint = {item.checkpoint_id: item for item in
            CapstoneStudentCheckpoint.objects.filter(capstone_project=project, checkpoint__plan=plan)
            .select_related('checkpoint')
            .prefetch_related('submissions__review', 'submissions__files', 'submissions__links', 'ticks')} if plan else {}
    else:
        plan, definitions, progress_by_checkpoint = preloaded
    rows = []
    for checkpoint in definitions:
        progress = progress_by_checkpoint.get(checkpoint.pk)
        submissions = list(progress.submissions.all()) if progress else []
        ticks = list(progress.ticks.all()) if progress else []
        state = _checkpoint_state(progress, checkpoint, submissions=submissions, ticks=ticks)
        checked_ids = {tick.item_id for tick in ticks if tick.is_checked}
        rows.append({'checkpoint': checkpoint, 'progress': progress, 'state': state,
                     'label': ACADEMIC_STATE_LABELS[state], 'submissions': submissions,
                     'due_at': progress.due_at if progress else checkpoint.due_at,
                     'expectations': [(item, item.pk in checked_ids) for item in checkpoint.expectations.all() if item.is_active]})
    approved = sum(row['state'] == 'APPROVED' for row in rows)
    pending = sum(row['state'] == 'AWAITING_REVIEW' for row in rows)
    revision = sum(row['state'] == 'REVISION_REQUIRED' for row in rows)
    due = [row['due_at'] for row in rows if row['state'] != 'APPROVED']
    if revision:
        action = 'Danışman geri bildirimine göre yeni tesliminizi hazırlayın.'
    elif pending:
        action = 'Tesliminiz danışman değerlendirmesi bekliyor.'
    elif rows and approved == len(rows):
        action = 'Kontrol planı onaylandı; danışmanınızın proje tamamlama işlemini bekleyin.'
    elif rows:
        action = 'Sıradaki kontrol noktası için beklenenleri hazırlayıp teslim edin.'
    else:
        action = 'Danışmanınızın kontrol planını oluşturmasını bekleyin.'
    completed = bool(project.completed_at or project.project.development_status == 'completed')
    if completed:
        action = 'Bitirme projeniz tamamlandı. Proje vitrininizi güncelleyebilirsiniz.'
    elif not project.project.advisor_id:
        action = 'Yeni danışman atamasını bekleyin. Akademik işlemler bu süre boyunca durduruldu.'
    current_stage = ('Tamamlandı' if completed else next(
        (row['checkpoint'].title for row in rows if row['state'] != 'APPROVED'),
        'Danışman onayı bekleniyor' if rows else 'Kontrol planı bekleniyor'))
    return {'plan': plan, 'rows': rows, 'approved': approved, 'total': len(rows),
            'percent': round(approved * 100 / len(rows)) if rows else 0,
            'current_stage': current_stage,
            'pending': pending, 'revision': revision,
            'overdue': sum(row['state'] == 'OVERDUE' for row in rows),
            'next_due': min(due) if due and not completed else None,
            'action': action, 'completed': completed,
            'completion_ready': bool(rows) and approved == len(rows) and not completed}


def send_due_reminders(*, now=None):
    """Idempotent reminder entry point for a future scheduler."""
    now = now or timezone.now()
    sent = 0
    projects = CapstoneProject.objects.filter(term__is_active=True, completed_at__isnull=True)
    projects = projects.select_related('project__created_by', 'project__advisor', 'term')
    for project in projects:
        if project.checkpoints.exists():
            continue
        for row in academic_overview(project)['rows']:
            if row['state'] in {'APPROVED', 'AWAITING_REVIEW'}:
                continue
            remaining = (row['due_at'] - now).total_seconds()
            if remaining > 7 * 86400:
                continue
            window = '7' if remaining > 2 * 86400 else '2' if remaining > 0 else 'late'
            message = (f'{row["checkpoint"].title} kontrol noktası için '
                       + ('son tarih geçti.' if window == 'late' else f'{window} gün veya daha az kaldı.'))
            key = f'capstone-reminder-{project.pk}-{row["checkpoint"].pk}-{row["due_at"].isoformat()}-{window}'
            before = project.project.created_by.notifications.filter(dedupe_key=key).exists()
            if not before:
                _notice(project.project.created_by, project.project.advisor, message, key)
                sent += 1
    return sent


@transaction.atomic
def tick_expectation(*, project, checkpoint, item, student, checked):
    if not can_submit_capstone(student, project) or item.checkpoint_id != checkpoint.pk:
        raise PermissionDenied
    progress = _progress(project, checkpoint)
    tick, _ = CapstoneChecklistTick.objects.update_or_create(progress=progress, item=item,
                                                               defaults={'is_checked': bool(checked)})
    return tick


@transaction.atomic
def extend_deadline(*, project, checkpoint, actor, due_at, reason):
    if not can_review_capstone(actor, project) or not (reason or '').strip():
        raise PermissionDenied
    progress = _progress(project, checkpoint)
    progress.override_due_at = due_at
    progress.extension_reason = reason.strip()
    progress.extension_changed_by = actor
    progress.extension_changed_at = timezone.now()
    progress.save(update_fields=['override_due_at', 'extension_reason', 'extension_changed_by', 'extension_changed_at', 'updated_at'])
    _audit(actor, 'capstone.deadline_extended', progress, project_id=project.pk, checkpoint_id=checkpoint.pk,
           new_due_at=due_at.isoformat(), reason_provided=True)
    _notice(project.project.created_by, actor, f'{checkpoint.title} kontrol noktası için ek süre verildi.',
            f'capstone-extension-{progress.pk}-{progress.extension_changed_at.timestamp()}')
    return progress


def _validate_file(upload, *, literature=False):
    if not upload or not getattr(upload, 'name', None) or upload.size <= 0:
        raise ValidationError('Geçerli bir dosya yükleyin.')
    validate_project_upload_size(upload)
    validate_project_upload_content(upload)
    if literature and detect_project_upload_type(upload) != 'document':
        raise ValidationError('Literatür raporu PDF olmalıdır.')


@transaction.atomic
def submit_checkpoint(*, project, checkpoint, student, note='', files=(), links=()):
    project = _lock_current_project(project)
    if not can_submit_capstone(student, project) or project.completed_at:
        raise PermissionDenied
    progress = _progress(project, checkpoint)
    latest = progress.submissions.order_by('-attempt_number').select_related('review').first()
    if latest and (not hasattr(latest, 'review') or latest.review.decision != 'REVISION_REQUIRED'):
        raise ValidationError('Bu kontrol noktası şu anda yeni teslim kabul etmiyor.')
    files = tuple(files)
    links = tuple(links)
    if not note.strip() and not files and not links:
        raise ValidationError('Teslim notu, dosya veya bağlantı ekleyin.')
    if len(files) > 10 or len(links) > 20:
        raise ValidationError('En fazla 10 dosya ve 20 bağlantı eklenebilir.')
    for upload in files:
        _validate_file(upload)
    for url in links:
        validate_public_website(url)
    attempt = CapstoneAcademicSubmission.objects.create(progress=progress, submitted_by=student,
        attempt_number=(latest.attempt_number + 1 if latest else 1), note=note)
    for upload in files:
        CapstoneAcademicSubmissionFile.objects.create(submission=attempt, file=upload)
    for url in links:
        CapstoneAcademicSubmissionLink.objects.create(submission=attempt, url=url)
    _audit(student, 'capstone.checkpoint_submitted', attempt, project_id=project.pk, checkpoint_id=checkpoint.pk)
    _notice(project.project.advisor, student, f'{checkpoint.title} için yeni teslim değerlendirme bekliyor.',
            f'capstone-academic-submit-{attempt.pk}', reverse('capstone:advisor_project_detail', args=[project.pk]))
    return attempt


@transaction.atomic
def review_checkpoint(*, submission, actor, decision, feedback):
    progress = CapstoneStudentCheckpoint.objects.select_related('capstone_project__project', 'checkpoint').get(pk=submission.progress_id)
    progress.capstone_project = _lock_current_project(progress.capstone_project)
    progress = _progress(progress.capstone_project, progress.checkpoint)
    if not can_review_capstone(actor, progress.capstone_project) or progress.capstone_project.completed_at:
        raise PermissionDenied
    submission = CapstoneAcademicSubmission.objects.select_for_update().get(pk=submission.pk, progress=progress)
    latest = progress.submissions.order_by('-attempt_number').first()
    if latest.pk != submission.pk or hasattr(submission, 'review'):
        raise ValidationError('Yalnız güncel ve bekleyen teslim değerlendirilebilir.')
    review = CapstoneAcademicReview.objects.create(submission=submission, reviewed_by=actor,
                                                    decision=decision, feedback=feedback)
    _audit(actor, 'capstone.checkpoint_reviewed', review, project_id=progress.capstone_project_id,
           checkpoint_id=progress.checkpoint_id, decision=decision)
    _notice(progress.capstone_project.project.created_by, actor,
            f'{progress.checkpoint.title} tesliminiz değerlendirildi.', f'capstone-academic-review-{review.pk}')
    return review


@transaction.atomic
def upload_literature(*, project, student, upload, note='', checkpoint=None):
    project = _lock_current_project(project)
    if not can_submit_capstone(student, project):
        raise PermissionDenied
    _validate_file(upload, literature=True)
    if checkpoint and (not checkpoint.is_active or checkpoint.plan.term_id != project.term_id or checkpoint.plan.advisor_id != project.project.advisor_id):
        raise PermissionDenied
    version = CapstoneLiteratureVersion.objects.create(capstone_project=project, checkpoint=checkpoint,
        uploaded_by=student, version=(project.literature_versions.aggregate(Max('version'))['version__max'] or 0) + 1,
        file=upload, note=note)
    _audit(student, 'capstone.literature_uploaded', version, project_id=project.pk, version=version.version)
    _notice(project.project.advisor, student, 'Yeni literatür raporu sürümü yüklendi.',
            f'capstone-literature-{version.pk}', reverse('capstone:advisor_project_detail', args=[project.pk]))
    return version


@transaction.atomic
def review_literature(*, version, actor, decision, feedback):
    version = CapstoneLiteratureVersion.objects.select_for_update().select_related('capstone_project__project').get(pk=version.pk)
    if not can_review_capstone(actor, version.capstone_project) or hasattr(version, 'review'):
        raise PermissionDenied
    review = CapstoneLiteratureReview.objects.create(version=version, reviewed_by=actor,
                                                      decision=decision, feedback=feedback)
    _audit(actor, 'capstone.literature_reviewed', review, version_id=version.pk, decision=decision)
    _notice(version.capstone_project.project.created_by, actor, 'Literatür raporunuz değerlendirildi.',
            f'capstone-literature-review-{review.pk}')
    return review


@transaction.atomic
def create_help_request(*, project, student, subject, description, checkpoint=None, upload=None):
    project = _lock_current_project(project)
    if not can_submit_capstone(student, project):
        raise PermissionDenied
    if checkpoint and (not checkpoint.is_active or checkpoint.plan.term_id != project.term_id or checkpoint.plan.advisor_id != project.project.advisor_id):
        raise PermissionDenied
    if upload:
        _validate_file(upload)
    item = CapstoneHelpRequest.objects.create(capstone_project=project, checkpoint=checkpoint,
                                               subject=subject, description=description)
    if upload:
        CapstoneHelpAttachment.objects.create(request=item, file=upload)
    _audit(student, 'capstone.help_requested', item, project_id=project.pk)
    _notice(project.project.advisor, student, 'Yeni bir yardım talebi var.', f'capstone-help-{item.pk}',
            reverse('capstone:advisor_project_detail', args=[project.pk]))
    return item


@transaction.atomic
def reply_help_request(*, request_item, actor, content):
    item = CapstoneHelpRequest.objects.select_for_update().select_related('capstone_project__project').get(pk=request_item.pk)
    project = item.capstone_project
    if not (can_submit_capstone(actor, project) or can_review_capstone(actor, project)) or item.resolved_at:
        raise PermissionDenied
    if not content.strip():
        raise ValidationError('Yanıt boş olamaz.')
    message = CapstoneHelpMessage.objects.create(request=item, author=actor, content=content.strip())
    recipient = project.project.advisor if actor.pk == project.project.created_by_id else project.project.created_by
    _audit(actor, 'capstone.help_replied', message, help_request_id=item.pk)
    target_url = (reverse('capstone:advisor_project_detail', args=[project.pk]) + '#communication'
                  if recipient.pk == project.project.advisor_id else reverse('capstone:student_home') + '#communication')
    _notice(recipient, actor, 'Yardım talebine yeni yanıt geldi.',
            f'capstone-help-reply-{message.pk}', target_url)
    return message


@transaction.atomic
def resolve_help_request(*, request_item, actor):
    item = CapstoneHelpRequest.objects.select_for_update().select_related('capstone_project__project').get(pk=request_item.pk)
    if not (can_submit_capstone(actor, item.capstone_project) or can_review_capstone(actor, item.capstone_project)):
        raise PermissionDenied
    if item.resolved_at:
        return item
    item.resolved_at, item.resolved_by = timezone.now(), actor
    item.save(update_fields=['resolved_at', 'resolved_by'])
    _audit(actor, 'capstone.help_resolved', item, project_id=item.capstone_project_id)
    return item


def help_state(item):
    if item.resolved_at:
        return 'Çözüldü'
    cached = getattr(item, '_prefetched_objects_cache', {}).get('messages')
    if cached is None:
        last = item.messages.order_by('-created_at', '-pk').first()
    else:
        messages = list(cached)
        last = messages[-1] if messages else None
    if not last:
        return 'Açık'
    return 'Akademisyen Yanıtladı' if last.author_id != item.capstone_project.project.created_by_id else 'Açık'


@transaction.atomic
def request_meeting(*, project, student, subject, description, availability_note, checkpoint=None):
    project = _lock_current_project(project)
    if not can_submit_capstone(student, project):
        raise PermissionDenied
    if checkpoint and (not checkpoint.is_active or checkpoint.plan.term_id != project.term_id or checkpoint.plan.advisor_id != project.project.advisor_id):
        raise PermissionDenied
    item = CapstoneMeetingRequest.objects.create(capstone_project=project, checkpoint=checkpoint,
        subject=subject, description=description, availability_note=availability_note)
    _audit(student, 'capstone.meeting_requested', item, project_id=project.pk)
    _notice(project.project.advisor, student, 'Yeni bir görüşme talebi var.', f'capstone-meeting-{item.pk}',
            reverse('capstone:advisor_project_detail', args=[project.pk]))
    return item


@transaction.atomic
def decide_meeting(*, meeting, actor, decision, scheduled_at=None, note=''):
    item = CapstoneMeetingRequest.objects.select_for_update().select_related('capstone_project__project').get(pk=meeting.pk)
    if not can_review_capstone(actor, item.capstone_project) or item.status not in {
        item.Status.REQUESTED, item.Status.SCHEDULED}:
        raise PermissionDenied
    if decision == 'schedule':
        if item.status != item.Status.REQUESTED:
            raise ValidationError('Planlanmış görüşme yeniden planlanamaz.')
        if scheduled_at is None or scheduled_at <= timezone.now():
            raise ValidationError('Gelecekte bir görüşme tarihi seçin.')
        item.status, item.scheduled_at = item.Status.SCHEDULED, scheduled_at
    elif decision == 'cancel':
        if not note.strip():
            raise ValidationError('Ret gerekçesi zorunludur.')
        item.status, item.decision_note = item.Status.CANCELLED, note.strip()
    else:
        raise ValidationError('Geçersiz karar.')
    item.save(update_fields=['status', 'scheduled_at', 'decision_note', 'updated_at'])
    _audit(actor, 'capstone.meeting_scheduled' if decision == 'schedule' else 'capstone.meeting_cancelled', item,
           project_id=item.capstone_project_id)
    _notice(item.capstone_project.project.created_by, actor,
            'Görüşmeniz planlandı.' if decision == 'schedule' else 'Görüşme talebiniz yanıtlandı.',
            f'capstone-meeting-decision-{item.pk}')
    return item


@transaction.atomic
def record_meeting(*, meeting, actor, content):
    item = CapstoneMeetingRequest.objects.select_for_update().select_related('capstone_project__project').get(pk=meeting.pk)
    if not can_review_capstone(actor, item.capstone_project) or item.status != item.Status.SCHEDULED or not content.strip():
        raise PermissionDenied
    note = CapstoneMeetingNote.objects.create(meeting=item, author=actor, content=content.strip())
    item.status = item.Status.HELD
    item.save(update_fields=['status', 'updated_at'])
    _audit(actor, 'capstone.meeting_held', note, meeting_id=item.pk)
    _notice(item.capstone_project.project.created_by, actor, 'Görüşme notu eklendi.', f'capstone-meeting-note-{item.pk}')
    return note


def add_private_note(*, project, actor, content):
    if not (_teacher(actor) and project.project.advisor_id == actor.pk) or not content.strip():
        raise PermissionDenied
    note = CapstoneAdvisorPrivateNote.objects.create(capstone_project=project, advisor=actor, content=content.strip())
    _audit(actor, 'capstone.advisor_note_created', note, project_id=project.pk)
    return note


@transaction.atomic
def save_plan_template(*, plan, actor, title):
    if not (_teacher(actor) and plan.advisor_id == actor.pk):
        raise PermissionDenied
    template = CapstonePlanTemplate.objects.create(advisor=actor, title=title)
    for checkpoint in plan.definitions.filter(is_active=True).prefetch_related('expectations'):
        copied = CapstoneTemplateCheckpoint.objects.create(template=template, title=checkpoint.title,
                                                            description=checkpoint.description, order=checkpoint.order)
        for expectation in checkpoint.expectations.filter(is_active=True):
            CapstoneTemplateExpectation.objects.create(checkpoint=copied, title=expectation.title, order=expectation.order)
    _audit(actor, 'capstone.plan_template_saved', template, plan_id=plan.pk)
    return template


@transaction.atomic
def apply_plan_template(*, plan, template, actor, due_dates):
    plan = CapstonePlan.objects.select_for_update().get(pk=plan.pk)
    if not (_teacher(actor) and plan.advisor_id == actor.pk and template.advisor_id == actor.pk):
        raise PermissionDenied
    if plan.definitions.exists():
        raise ValidationError('Şablon yalnız boş bir plana uygulanabilir.')
    definitions = list(template.definitions.prefetch_related('expectations'))
    if set(due_dates) != {item.pk for item in definitions}:
        raise ValidationError('Her kontrol noktası için yeni dönem tarihi gereklidir.')
    for source in definitions:
        checkpoint = CapstonePlanCheckpoint.objects.create(plan=plan, title=source.title,
            description=source.description, order=source.order, due_at=due_dates[source.pk])
        for expectation in source.expectations.all():
            CapstoneChecklistItem.objects.create(checkpoint=checkpoint, title=expectation.title, order=expectation.order)
    _audit(actor, 'capstone.plan_template_applied', plan, template_id=template.pk)
    return plan
