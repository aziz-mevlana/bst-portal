import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from core.audit import record_audit_event
from core.notifications import create_notification

from .models import Project, ProjectRequest, ProjectRequestApplication


logger = logging.getLogger(__name__)


@transaction.atomic
def accept_project_request_application(*, application_id, reviewer, review_note=''):
    """Accept an application exactly once and create its project atomically."""

    request_id = (
        ProjectRequestApplication.objects.filter(pk=application_id)
        .values_list('project_request_id', flat=True)
        .first()
    )
    if request_id is None:
        raise ProjectRequestApplication.DoesNotExist

    project_request = (
        ProjectRequest.objects.select_for_update()
        .select_related('teacher', 'project_type', 'created_project')
        .get(pk=request_id)
    )
    application = (
        ProjectRequestApplication.objects.select_for_update()
        .select_related('student')
        .get(pk=application_id, project_request=project_request)
    )

    if not (reviewer.is_staff or reviewer.is_superuser or project_request.teacher_id == reviewer.id):
        raise PermissionDenied('Bu başvuruyu kabul etme yetkiniz yok.')

    if project_request.created_project_id:
        if application.status == 'accepted':
            return project_request.created_project, False
        raise ValidationError('Bu istek için daha önce bir öğrenci seçilmiş.')

    if project_request.status not in {'open', 'reviewing'}:
        raise ValidationError('İstek başvuru kabul etmeye uygun durumda değil.')
    if project_request.is_past_deadline:
        raise ValidationError('Başvuru süresi sona ermiş.')
    if application.status != 'pending':
        raise ValidationError('Yalnızca bekleyen bir başvuru kabul edilebilir.')
    if not project_request.project_type_id:
        raise ValidationError('İstek için proje türü belirlenmemiş.')

    project = Project.objects.create(
        project_request=project_request,
        project_type=project_request.project_type,
        creation_source='ACADEMIC_REQUEST',
        title=project_request.title,
        advisor=project_request.teacher,
        description=project_request.description,
        expected_output=project_request.expected_output,
        created_by=application.student,
        approval_status='approved',
        development_status='idea',
        visibility='private',
        # Transitional fields used by old screens.
        status='approved',
        is_private=True,
    )
    project.team.add(application.student)
    project.categories.set(project_request.categories.all())
    project.technologies.set(project_request.technologies.all())

    now = timezone.now()
    application.status = 'accepted'
    application.reviewed_by = reviewer
    application.review_note = review_note
    application.reviewed_at = now
    application.save(
        update_fields=['status', 'reviewed_by', 'review_note', 'reviewed_at', 'updated_at']
    )
    rejected_applications = list(
        project_request.applications.filter(status='pending')
        .exclude(pk=application.pk)
        .select_related('student')
    )
    project_request.applications.filter(status='pending').exclude(pk=application.pk).update(
        status='rejected',
        reviewed_by=reviewer,
        review_note='Başka bir başvuru kabul edildi.',
        reviewed_at=now,
        updated_at=now,
    )
    project_request.status = 'student_selected'
    project_request.created_project = project
    project_request.save(update_fields=['status', 'created_project', 'updated_at'])

    create_notification(
        recipient=application.student,
        actor=reviewer,
        notification_type='application_accepted',
        message=f'“{project_request.title}” başvurun kabul edildi ve projen oluşturuldu.',
        target_url=project.get_absolute_url(),
    )
    for rejected in rejected_applications:
        create_notification(
            recipient=rejected.student,
            actor=reviewer,
            notification_type='application_rejected',
            message=f'“{project_request.title}” için başka bir başvuru kabul edildi.',
            target_url=f'/projects/requests/{project_request.pk}/',
        )

    record_audit_event(
        actor=reviewer,
        action='project_request.application_accepted',
        target=application,
        metadata={
            'project_request_id': project_request.pk,
            'project_id': project.pk,
            'student_id': application.student_id,
        },
    )
    record_audit_event(
        actor=reviewer,
        action='project.auto_created',
        target=project,
        metadata={'project_request_id': project_request.pk},
    )

    logger.info(
        'project_request_application_accepted',
        extra={
            'project_request_id': project_request.pk,
            'application_id': application.pk,
            'project_id': project.pk,
            'reviewer_id': reviewer.pk,
            'student_id': application.student_id,
        },
    )
    return project, True
