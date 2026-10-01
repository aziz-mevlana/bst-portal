"""Course assignment enrollment, teams and shared plan operations."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.policies import is_admin, is_teacher, role_of
from core.audit import record_audit_event
from core.notifications import create_notification

from .course_work_models import (
    CourseAssignmentCheckpoint, CourseAssignmentExpectation, CourseProjectAssignment,
    CourseProjectParticipation, CourseProjectTeam, CourseProjectWork, invitation_token,
)
from .models import CourseInstructor, Project, ProjectMilestone, ProjectRepository, ProjectType


def can_manage_assignment(user, assignment):
    return bool(user.is_authenticated and user.is_active and (
        is_admin(user) or is_teacher(user) and assignment.instructor_id == user.pk and
        CourseInstructor.objects.filter(course_id=assignment.course_id, instructor=user, is_active=True).exists()
    ))


def locked_assignment(assignment_id):
    try:
        return CourseProjectAssignment.objects.select_for_update(of=("self",)).get(pk=assignment_id)
    except CourseProjectAssignment.DoesNotExist:
        raise ValidationError("Çalışma kalıcı olarak silindi.")


def require_active_assignment(assignment):
    if not assignment.is_active:
        raise ValidationError("Bu çalışma iptal edildi veya kapalı; geçmiş salt okunurdur.")


def lock_assignment_for_project(project_id):
    """All academic writes take assignment before project/milestone locks."""
    assignment_id = CourseProjectWork.objects.filter(project_id=project_id).values_list("assignment_id", flat=True).first()
    if assignment_id:
        assignment = locked_assignment(assignment_id)
        require_active_assignment(assignment)
        return assignment


def can_view_work(user, work):
    if can_manage_assignment(user, work.assignment):
        return True
    if not user.is_authenticated or not user.is_active:
        return False
    participants = CourseProjectParticipation.objects.filter(assignment=work.assignment, student=user)
    return participants.filter(student_id=work.owner_id).exists() if work.owner_id else participants.filter(team_id=work.team_id).exists()


@transaction.atomic
def create_assignment(*, instructor, course, **values):
    assignment = CourseProjectAssignment(course=course, instructor=instructor, **values)
    if not can_manage_assignment(instructor, assignment):
        raise PermissionDenied
    assignment.save()
    record_audit_event(actor=instructor, action='course.assignment_created', target=assignment,
                       metadata={'course_id': course.pk})
    return assignment


@transaction.atomic
def rotate_invitation(*, assignment, actor, enabled=True):
    assignment = locked_assignment(assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    require_active_assignment(assignment)
    assignment.invitation_token = invitation_token()
    assignment.invitation_enabled = enabled
    assignment.save(update_fields=['invitation_token', 'invitation_enabled', 'updated_at'])
    record_audit_event(actor=actor, action='course.assignment_invitation_rotated', target=assignment)
    return assignment


@transaction.atomic
def join_assignment(*, token, student):
    assignment = CourseProjectAssignment.objects.select_for_update(of=('self',)).select_related('course', 'instructor').get(invitation_token=token)
    if not student.is_authenticated or not student.is_active or role_of(student) not in {'student', 'staff_student'}:
        raise PermissionDenied
    existing = CourseProjectParticipation.objects.filter(assignment=assignment, student=student).first()
    if existing:
        return existing
    if not assignment.course.is_active or not can_manage_assignment(assignment.instructor, assignment):
        raise ValidationError('Bu çalışma artık öğrenci kabul etmiyor.')
    if not assignment.is_active or not assignment.invitation_enabled or timezone.now() > assignment.join_deadline:
        raise ValidationError('Katılım bağlantısının süresi dolmuş veya bağlantı kapatılmış.')
    participation, _ = CourseProjectParticipation.objects.get_or_create(assignment=assignment, student=student)
    return participation


def _open_participation(*, assignment, student, require_join_open=True):
    assignment = locked_assignment(assignment.pk)
    if not assignment.is_active or require_join_open and timezone.now() > assignment.join_deadline:
        raise ValidationError('Katılım süresi sona erdi.')
    return CourseProjectParticipation.objects.select_for_update().get(assignment=assignment, student=student), assignment


@transaction.atomic
def create_team(*, assignment, student, name):
    participation, assignment = _open_participation(assignment=assignment, student=student)
    if assignment.mode != assignment.Mode.GROUP or participation.team_id or not name.strip():
        raise ValidationError('Ekip oluşturulamıyor.')
    team = CourseProjectTeam.objects.create(assignment=assignment, name=name.strip(), created_by=student)
    participation.team = team
    participation.save(update_fields=['team'])
    record_audit_event(actor=student, action='course.team_created', target=team,
                       metadata={'assignment_id': assignment.pk})
    return team


@transaction.atomic
def join_team(*, assignment, student, team_id):
    participation, assignment = _open_participation(assignment=assignment, student=student)
    team = CourseProjectTeam.objects.select_for_update().get(pk=team_id, assignment=assignment)
    if assignment.mode != assignment.Mode.GROUP or participation.team_id and participation.team_id != team.pk:
        raise ValidationError('Bu ekibe katılamazsınız.')
    if participation.team_id == team.pk:
        return team
    if team.participants.count() >= assignment.max_team_size:
        raise ValidationError('Ekip kapasitesi doldu.')
    participation.team = team
    participation.save(update_fields=['team'])
    work = CourseProjectWork.objects.filter(team=team).select_related('project').first()
    if work:
        work.project.team.add(student)
    record_audit_event(actor=student, action='course.team_joined', target=team,
                       metadata={'assignment_id': assignment.pk})
    return team


@transaction.atomic
def override_team_member(*, assignment, actor, student_id, team_id, reason):
    """A course instructor may correct team membership after enrollment closes."""
    assignment = locked_assignment(assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    require_active_assignment(assignment)
    if assignment.mode != assignment.Mode.GROUP or not reason.strip():
        raise ValidationError('Ekip değişikliği için gerekçe zorunludur.')
    participation = CourseProjectParticipation.objects.select_for_update().select_related('student').get(
        assignment=assignment, student_id=student_id)
    target = (CourseProjectTeam.objects.select_for_update().get(assignment=assignment, pk=team_id)
              if team_id else None)
    old_team_id = participation.team_id
    if old_team_id == (target.pk if target else None):
        return participation
    old_work = CourseProjectWork.objects.select_related('project').filter(team_id=old_team_id).first() if old_team_id else None
    if old_work and old_work.project.created_by_id == student_id:
        raise ValidationError('Proje kurucusu aktif ekip projesinden çıkarılamaz.')
    if old_work and old_work.team.participants.count() <= assignment.min_team_size:
        raise ValidationError('Aktif ekip projesi asgari üye sayısının altına düşürülemez.')
    if target and target.participants.count() >= assignment.max_team_size:
        raise ValidationError('Ekip kapasitesi doldu.')
    if old_work:
        old_work.project.team.remove(participation.student)
    participation.team = target
    participation.save(update_fields=['team'])
    new_work = CourseProjectWork.objects.select_related('project').filter(team=target).first() if target else None
    if new_work:
        new_work.project.team.add(participation.student)
    record_audit_event(actor=actor, action='course.team_membership_overridden', target=participation,
        metadata={'assignment_id': assignment.pk, 'student_id': student_id,
                  'old_team_id': old_team_id, 'new_team_id': target.pk if target else None,
                  'reason': reason.strip()})
    create_notification(recipient=participation.student, actor=actor, notification_type='project_update',
        message='Ders Projesi Çalışması ekip üyeliğiniz akademisyen tarafından güncellendi.',
        target_url=reverse('projects:course_invitation', args=[assignment.invitation_token]),
        dedupe_key=f'course-team-override-{participation.pk}-{timezone.now().timestamp()}')
    return participation


@transaction.atomic
def create_work(*, assignment, student, title, idea, repository_path=''):
    participation, assignment = _open_participation(assignment=assignment, student=student, require_join_open=False)
    if not title.strip() or not idea.strip():
        raise ValidationError('Proje adı ve çözüm fikri zorunludur.')
    if assignment.repository_required and not repository_path.strip():
        raise ValidationError('Bu çalışmada proje deposu zorunludur.')
    if repository_path.strip():
        ProjectRepository.parse_repository_path(repository_path)
    team = None
    if assignment.mode == assignment.Mode.GROUP:
        if not participation.team_id:
            raise ValidationError('Önce bir ekibe katılın.')
        team = CourseProjectTeam.objects.select_for_update().get(pk=participation.team_id, assignment=assignment)
        if team.created_by_id != student.pk:
            raise PermissionDenied
        if team.participants.count() < assignment.min_team_size:
            raise ValidationError('Ekip asgari üye sayısına ulaşmadı.')
        if CourseProjectWork.objects.filter(team=team).exists():
            raise ValidationError('Bu ekipın proje bilgileri zaten kaydedildi.')
    elif CourseProjectWork.objects.filter(assignment=assignment, owner=student).exists():
        raise ValidationError('Proje bilgileriniz zaten kaydedildi.')
    project_type = ProjectType.objects.get(code='COURSE')
    project = Project.objects.create(project_type=project_type, course=assignment.course,
        advisor=assignment.instructor, created_by=student, title=title.strip(), description=idea.strip(),
        creation_source='COURSE_ASSIGNMENT', status='in_progress', approval_status='approved',
        development_status='in_progress', visibility='private', is_private=True)
    work = CourseProjectWork.objects.create(assignment=assignment, project=project,
        team=team, owner=None if team else student)
    if team:
        project.team.set(team.participants.values_list('student_id', flat=True))
    if repository_path.strip():
        ProjectRepository.objects.create(project=project, repository_path=repository_path.strip())
    for definition in assignment.checkpoints.filter(is_active=True):
        ProjectMilestone.objects.create(project=project, assignment_checkpoint=definition,
            title='', order=definition.order, due_at=None, created_by=assignment.instructor)
    record_audit_event(actor=student, action='course.work_created', target=work,
                       metadata={'assignment_id': assignment.pk, 'project_id': project.pk})
    create_notification(recipient=assignment.instructor, actor=student, notification_type='project_update',
        message=f'{project.title} ders projesi bilgileri tamamlandı.',
        target_url=reverse('projects:course_work_detail', args=[work.pk]),
        dedupe_key=f'course-work-created-{work.pk}')
    return work


@transaction.atomic
def save_checkpoint(*, assignment, actor, values, checkpoint=None):
    assignment = locked_assignment(assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    require_active_assignment(assignment)
    if checkpoint:
        checkpoint = CourseAssignmentCheckpoint.objects.select_for_update().get(pk=checkpoint.pk, assignment=assignment)
        previous_due = checkpoint.due_at
        previous_order = checkpoint.order
        if previous_order != values['order'] and checkpoint.project_progress.exists():
            raise ValidationError('Projeler başladıktan sonra kontrol noktası sırası değiştirilemez.')
        for field, value in values.items():
            setattr(checkpoint, field, value)
        checkpoint.save()
        action = 'course.checkpoint_updated'
    else:
        previous_due = None
        checkpoint = CourseAssignmentCheckpoint.objects.create(assignment=assignment, **values)
        for work in assignment.works.select_related('project'):
            ProjectMilestone.objects.create(project=work.project, assignment_checkpoint=checkpoint,
                title='', order=checkpoint.order, due_at=None, created_by=assignment.instructor)
        action = 'course.checkpoint_created'
    record_audit_event(actor=actor, action=action, target=checkpoint,
        metadata={'assignment_id': assignment.pk})
    if previous_due is not None and previous_due != checkpoint.due_at:
        record_audit_event(actor=actor, action='course.checkpoint_deadline_changed', target=checkpoint)
        for work in assignment.works.select_related('project__created_by'):
            recipients = [work.project.created_by]
            if work.team_id:
                recipients = [member.student for member in work.team.participants.select_related('student')]
            for student in recipients:
                create_notification(recipient=student, actor=actor, notification_type='project_update',
                    message=f'{checkpoint.title} kontrol noktasının tarihi değişti.',
                    target_url=reverse('projects:course_work_detail', args=[work.pk]),
                    dedupe_key=f'course-checkpoint-deadline-{checkpoint.pk}-{checkpoint.updated_at.timestamp()}')
    return checkpoint


@transaction.atomic
def add_expectation(*, checkpoint, actor, title):
    assignment = locked_assignment(checkpoint.assignment_id)
    require_active_assignment(assignment)
    checkpoint = CourseAssignmentCheckpoint.objects.select_for_update().get(pk=checkpoint.pk, assignment=assignment)
    checkpoint.assignment = assignment
    if not can_manage_assignment(actor, checkpoint.assignment) or not title.strip():
        raise PermissionDenied
    order = (checkpoint.expected_items.order_by('-order').values_list('order', flat=True).first() or 0) + 1
    item = CourseAssignmentExpectation.objects.create(checkpoint=checkpoint, title=title.strip(), order=order)
    record_audit_event(actor=actor, action='course.expectation_created', target=item)
    return item


EDIT_FIELDS = {'topic', 'purpose', 'expectations', 'mode', 'min_team_size', 'max_team_size',
               'join_deadline', 'starts_at', 'ends_at', 'repository_required'}


def _notify_participants(assignment, actor, message, key):
    for participation in assignment.participants.select_related(
        'student', 'student__communication_preferences'
    ).order_by('student_id'):
        create_notification(recipient=participation.student, actor=actor, notification_type='project_update',
            title=f'{assignment.course.code} Ders Projesi Çalışması', message=message,
            target_url=reverse('projects:course_invitation', args=[assignment.invitation_token]),
            dedupe_key=key, force=True)


def _lifecycle_message(assignment, actor, reason, action):
    """Keep every required notification field within the infrastructure's 300 characters."""
    name = actor.get_full_name() or actor.username
    message = (f'{assignment.course.code} Ders Projesi Çalışması {action}. '
               f'{assignment.course.name} · {name} · Gerekçe: {reason}')
    if len(message) <= 300:
        return message

    def shorten(value, limit):
        return value if len(value) <= limit else value[:limit - 1] + '…'

    prefix = (f'{assignment.course.code} Ders Projesi Çalışması {action}. '
              f'{shorten(assignment.course.name, 60)} · {shorten(name, 60)} · Gerekçe: ')
    return prefix + shorten(reason, 300 - len(prefix))


@transaction.atomic
def edit_assignment(*, assignment, actor, values):
    assignment = locked_assignment(assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    require_active_assignment(assignment)
    if set(values) - EDIT_FIELDS:
        raise ValidationError('Bu alanlar düzenlenemez.')
    changes = {key: {'before': str(getattr(assignment, key)), 'after': str(value)}
               for key, value in values.items() if getattr(assignment, key) != value}
    if not changes:
        return assignment
    for key, value in values.items():
        setattr(assignment, key, value)
    assignment.save()
    audit = record_audit_event(actor=actor, action='course.assignment_updated', target=assignment,
        metadata={'course_id': assignment.course_id, 'changes': changes})
    if set(changes) & {'join_deadline', 'starts_at', 'ends_at', 'repository_required', 'topic', 'purpose', 'expectations'}:
        _notify_participants(assignment, actor,
            f'{assignment.course.code} Ders Projesi Çalışmasının kapsamı veya tarihleri güncellendi. Çalışma ayrıntılarını inceleyin.',
            f'course-assignment-edited-{audit.pk}')
    return assignment


def _reason(reason):
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError('Gerekçe zorunludur.')
    if len(reason) > 2000:
        raise ValidationError('Gerekçe en fazla 2000 karakter olabilir.')
    return reason


def _version(current, expected):
    if current.lifecycle_version != expected:
        raise ValidationError('Çalışmanın durumu değişti. Sayfayı yenileyip tekrar deneyin.')


@transaction.atomic
def cancel_assignment(*, assignment, actor, reason, expected_version=None):
    expected_version = assignment.lifecycle_version if expected_version is None else expected_version
    assignment = locked_assignment(assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    reason = _reason(reason)
    if assignment.is_cancelled:
        return assignment, False
    require_active_assignment(assignment)
    _version(assignment, expected_version)
    assignment.is_active = False
    assignment.cancelled_at = timezone.now()
    assignment.cancelled_by = actor
    assignment.cancellation_reason = reason
    assignment.lifecycle_version += 1
    assignment.save()
    record_audit_event(actor=actor, action='course.assignment_cancelled', target=assignment,
        metadata={'course_id': assignment.course_id, 'reason': reason, 'version': assignment.lifecycle_version})
    _notify_participants(assignment, actor,
        _lifecycle_message(assignment, actor, reason, 'iptal edildi'),
        f'course-assignment-cancelled-{assignment.pk}-{assignment.lifecycle_version}')
    return assignment, True


@transaction.atomic
def reactivate_assignment(*, assignment, actor, reason, expected_version=None):
    expected_version = assignment.lifecycle_version if expected_version is None else expected_version
    assignment = locked_assignment(assignment.pk)
    if not actor.is_active or not is_admin(actor):
        raise PermissionDenied
    reason = _reason(reason)
    if assignment.is_active:
        return assignment, False
    if not assignment.is_cancelled:
        raise ValidationError('Yalnız iptal edilmiş çalışma yeniden aktifleştirilebilir.')
    _version(assignment, expected_version)
    assignment.is_active = True
    assignment.lifecycle_version += 1
    assignment.save()  # Full chronology, instructor and existing team validation.
    record_audit_event(actor=actor, action='course.assignment_reactivated', target=assignment,
        metadata={'course_id': assignment.course_id, 'reason': reason, 'version': assignment.lifecycle_version})
    _notify_participants(assignment, actor,
        _lifecycle_message(assignment, actor, reason, 'yeniden aktifleştirildi'),
        f'course-assignment-reactivated-{assignment.pk}-{assignment.lifecycle_version}')
    return assignment, True


def assignment_has_history(assignment):
    if any((assignment.participants.exists(), assignment.teams.exists(), assignment.works.exists(),
            assignment.checkpoints.exists(), assignment.cancelled_at is not None)):
        return True
    # Administrative corrections can remove rows while immutable academic audit remains.
    from core.models import AuditLog
    return AuditLog.objects.filter(metadata__assignment_id=assignment.pk, action__in=(
        'course.team_created', 'course.team_joined', 'course.team_membership_overridden',
        'course.work_created', 'course.checkpoint_created', 'course.checkpoint_updated',
        'course.checkpoint_deadline_changed',
    )).exists()


@transaction.atomic
def delete_empty_assignment(*, assignment, actor, reason):
    assignment = locked_assignment(assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    reason = _reason(reason)
    if assignment_has_history(assignment):
        raise ValidationError('Katılım veya akademik geçmiş bulunan çalışma silinemez. İptal Et aksiyonunu kullanın.')
    snapshot = {'assignment_id': assignment.pk, 'course_id': assignment.course_id,
                'course_code': assignment.course.code, 'topic': assignment.topic, 'reason': reason}
    record_audit_event(actor=actor, action='course.assignment_deleted', target=assignment, metadata=snapshot)
    assignment.delete()
    return snapshot


@transaction.atomic
def purge_assignment(*, assignment, actor, reason):
    """Admin-only graph purge; lock root first, retain audit snapshots, clean files after commit."""
    if not actor.is_active or not is_admin(actor):
        raise PermissionDenied
    reason = _reason(reason)
    assignment = locked_assignment(assignment.pk)
    from django.apps import apps
    from django.db import models
    from django.db.models import Q
    from django.db.models.deletion import Collector
    from core.models import Notification
    from .models import (ProjectMilestoneReview, ProjectMilestoneSubmission,
                         ProjectMilestoneSubmissionFile, ProjectMilestoneSubmissionLink)
    import logging

    project_ids = list(assignment.works.values_list('project_id', flat=True))
    work_ids = list(assignment.works.values_list('pk', flat=True))
    # A malformed cross-assignment reference must never expand deletion scope.
    if ProjectMilestone.objects.filter(assignment_checkpoint__assignment=assignment).exclude(project_id__in=project_ids).exists():
        raise ValidationError('Başka projeye bağlı kontrol noktası bulundu; kalıcı silme durduruldu.')
    snapshot = {'assignment_id': assignment.pk, 'course_id': assignment.course_id,
        'course_code': assignment.course.code, 'course_name': assignment.course.name,
        'instructor_id': assignment.instructor_id, 'topic': assignment.topic, 'reason': reason,
        'participant_count': assignment.participants.count(), 'team_count': assignment.teams.count(),
        'work_count': len(work_ids), 'project_ids': project_ids}
    submissions = ProjectMilestoneSubmission.objects.filter(milestone__project_id__in=project_ids)
    files = [(item.file.storage, item.file.name) for item in
             ProjectMilestoneSubmissionFile.objects.filter(submission__in=submissions) if item.file]
    from .models import ProjectMilestoneSubmissionReference
    from .course_work_models import CoursePrivateEvaluation
    CoursePrivateEvaluation.objects.filter(review__submission__in=submissions).delete()
    ProjectMilestoneSubmissionReference.objects.filter(submission__in=submissions).delete()
    ProjectMilestoneReview.objects.filter(submission__in=submissions).delete()
    ProjectMilestoneSubmissionLink.objects.filter(submission__in=submissions).delete()
    ProjectMilestoneSubmissionFile.objects.filter(submission__in=submissions).delete()
    submissions.delete()
    # Collector follows the real Project graph, including media, repositories and workflow history.
    collector = Collector(using='default')
    collector.collect(Project.objects.filter(pk__in=project_ids))
    for model, instances in collector.data.items():
        for field in model._meta.fields:
            if isinstance(field, models.FileField):
                files.extend((value.storage, value.name) for obj in instances
                             if (value := getattr(obj, field.name)))
    for queryset in collector.fast_deletes:
        for field in queryset.model._meta.fields:
            if isinstance(field, models.FileField):
                files.extend((value.storage, value.name) for obj in queryset
                             if (value := getattr(obj, field.name)))
    collector.delete()
    assignment.participants.all().delete()
    assignment.teams.all().delete()
    CourseAssignmentExpectation.objects.filter(checkpoint__assignment=assignment).delete()
    assignment.checkpoints.all().delete()
    urls = [reverse('projects:course_invitation', args=[assignment.invitation_token]),
            reverse('projects:course_assignment_detail', args=[assignment.pk])]
    urls += [reverse('projects:course_work_detail', args=[pk]) for pk in work_ids]
    urls += [reverse('projects:project_detail', args=[pk]) for pk in project_ids]
    scope = Q(pk__in=[])
    for url in urls:
        scope |= Q(target_url=url) | Q(target_url__startswith=url + '#')
    Notification.objects.filter(scope).delete()
    record_audit_event(actor=actor, action='course.assignment_purged', target=assignment, metadata=snapshot)
    assignment.delete()

    def cleanup():
        file_fields = [(model, field) for model in apps.get_models() for field in model._meta.fields
                       if isinstance(field, models.FileField)]
        seen = set()
        for storage, name in files:
            if not name or (id(storage), name) in seen:
                continue
            seen.add((id(storage), name))
            try:
                # Conservatively preserve any still referenced name, including other assignments/apps.
                if any(model.objects.filter(**{field.name: name}).exists() for model, field in file_fields):
                    continue
                storage.delete(name)
            except Exception:
                logging.getLogger(__name__).exception('Ders çalışması sonrası dosya temizlenemedi: %s', name)
    transaction.on_commit(cleanup)
    return snapshot
