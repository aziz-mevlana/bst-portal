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
    assignment = CourseProjectAssignment.objects.select_for_update().get(pk=assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    assignment.invitation_token = invitation_token()
    assignment.invitation_enabled = enabled
    assignment.save(update_fields=['invitation_token', 'invitation_enabled', 'updated_at'])
    record_audit_event(actor=actor, action='course.assignment_invitation_rotated', target=assignment)
    return assignment


@transaction.atomic
def join_assignment(*, token, student):
    assignment = CourseProjectAssignment.objects.select_for_update().select_related('course', 'instructor').get(invitation_token=token)
    if not student.is_authenticated or not student.is_active or role_of(student) not in {'student', 'staff_student'}:
        raise PermissionDenied
    if not assignment.course.is_active or not can_manage_assignment(assignment.instructor, assignment):
        raise ValidationError('Bu çalışma artık öğrenci kabul etmiyor.')
    if not assignment.is_active or not assignment.invitation_enabled or timezone.now() > assignment.join_deadline:
        raise ValidationError('Katılım bağlantısının süresi dolmuş veya bağlantı kapatılmış.')
    participation, _ = CourseProjectParticipation.objects.get_or_create(assignment=assignment, student=student)
    return participation


def _open_participation(*, assignment, student, require_join_open=True):
    assignment = CourseProjectAssignment.objects.select_for_update().get(pk=assignment.pk)
    if not assignment.is_active or require_join_open and timezone.now() > assignment.join_deadline:
        raise ValidationError('Katılım süresi sona erdi.')
    return CourseProjectParticipation.objects.select_for_update().get(assignment=assignment, student=student), assignment


@transaction.atomic
def create_team(*, assignment, student, name):
    participation, assignment = _open_participation(assignment=assignment, student=student)
    if assignment.mode != assignment.Mode.GROUP or participation.team_id or not name.strip():
        raise ValidationError('Takım oluşturulamıyor.')
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
        raise ValidationError('Bu takıma katılamazsınız.')
    if participation.team_id == team.pk:
        return team
    if team.participants.count() >= assignment.max_team_size:
        raise ValidationError('Takım kapasitesi doldu.')
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
    assignment = CourseProjectAssignment.objects.select_for_update().get(pk=assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    if assignment.mode != assignment.Mode.GROUP or not reason.strip():
        raise ValidationError('Takım değişikliği için gerekçe zorunludur.')
    participation = CourseProjectParticipation.objects.select_for_update().select_related('student').get(
        assignment=assignment, student_id=student_id)
    target = (CourseProjectTeam.objects.select_for_update().get(assignment=assignment, pk=team_id)
              if team_id else None)
    old_team_id = participation.team_id
    if old_team_id == (target.pk if target else None):
        return participation
    old_work = CourseProjectWork.objects.select_related('project').filter(team_id=old_team_id).first() if old_team_id else None
    if old_work and old_work.project.created_by_id == student_id:
        raise ValidationError('Proje kurucusu aktif takım projesinden çıkarılamaz.')
    if old_work and old_work.team.participants.count() <= assignment.min_team_size:
        raise ValidationError('Aktif takım projesi asgari üye sayısının altına düşürülemez.')
    if target and target.participants.count() >= assignment.max_team_size:
        raise ValidationError('Takım kapasitesi doldu.')
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
        message='Ders Projesi Çalışması takım üyeliğiniz akademisyen tarafından güncellendi.',
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
            raise ValidationError('Önce bir takıma katılın.')
        team = CourseProjectTeam.objects.select_for_update().get(pk=participation.team_id, assignment=assignment)
        if team.created_by_id != student.pk:
            raise PermissionDenied
        if team.participants.count() < assignment.min_team_size:
            raise ValidationError('Takım asgari üye sayısına ulaşmadı.')
        if CourseProjectWork.objects.filter(team=team).exists():
            raise ValidationError('Bu takımın proje bilgileri zaten kaydedildi.')
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
    assignment = CourseProjectAssignment.objects.select_for_update().get(pk=assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
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
    checkpoint = CourseAssignmentCheckpoint.objects.select_for_update().select_related('assignment').get(pk=checkpoint.pk)
    if not can_manage_assignment(actor, checkpoint.assignment) or not title.strip():
        raise PermissionDenied
    order = (checkpoint.expected_items.order_by('-order').values_list('order', flat=True).first() or 0) + 1
    item = CourseAssignmentExpectation.objects.create(checkpoint=checkpoint, title=title.strip(), order=order)
    record_audit_event(actor=actor, action='course.expectation_created', target=item)
    return item
