from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from core.audit import record_audit_event
from core.notifications import create_notification
from accounts.validators import validate_public_website
from .models import (
    CourseInstructor, ProjectMilestone, ProjectMilestoneReview,
    ProjectMilestoneSubmission, ProjectMilestoneSubmissionFile,
    ProjectMilestoneSubmissionLink, validate_project_upload_content,
)
from .milestone_policies import can_manage_project_milestones, can_submit_project_milestone, can_review_project_milestone


def _notify(users, *, actor, message, url, key):
    for user in {user.pk: user for user in users if user}.values():
        create_notification(recipient=user, actor=actor, notification_type='project_milestone',
                            message=message, target_url=url, dedupe_key=key)


@transaction.atomic
def save_milestone(*, project, actor, values, milestone=None):
    project = type(project).objects.select_for_update().select_related('project_type').get(pk=project.pk)
    if not can_manage_project_milestones(actor, project):
        raise PermissionDenied
    if milestone:
        milestone = ProjectMilestone.objects.select_for_update().get(pk=milestone.pk, project=project)
        previous_deadline = milestone.due_at
        for field, value in values.items():
            setattr(milestone, field, value)
    else:
        previous_deadline = None
        milestone = ProjectMilestone(project=project, created_by=actor, **values)
    milestone._acting_user = actor
    was_created = not milestone.pk
    milestone.save()
    record_audit_event(actor=actor, action='project.milestone.created' if was_created else 'project.milestone.updated', target=milestone,
                       metadata={'project_id': project.pk})
    if not was_created and previous_deadline != milestone.due_at:
        record_audit_event(actor=actor, action='project.milestone.deadline_changed', target=milestone,
                           metadata={'project_id': project.pk})
    return milestone


@transaction.atomic
def delete_milestone(*, milestone, actor):
    milestone = ProjectMilestone.objects.select_for_update().select_related(
        'project', 'project__project_type'
    ).get(pk=milestone.pk)
    if not can_manage_project_milestones(actor, milestone.project):
        raise PermissionDenied
    if milestone.submissions.exists():
        raise ValidationError('Teslim veya değerlendirme geçmişi bulunan proje aşaması silinemez.')
    project_id, milestone_id = milestone.project_id, milestone.pk
    record_audit_event(actor=actor, action='project.milestone.deleted', target=milestone,
                       metadata={'project_id': project_id, 'milestone_id': milestone_id})
    milestone.delete()


def submit_milestone(*, milestone, actor, note='', links=(), files=()):
    saved_files = []
    try:
        return _submit_milestone_atomic(milestone=milestone, actor=actor, note=note,
                                        links=links, files=files, saved_files=saved_files)
    except Exception:
        for storage, name in saved_files:
            try:
                storage.delete(name)
            except OSError:
                pass
        raise


@transaction.atomic
def _submit_milestone_atomic(*, milestone, actor, note, links, files, saved_files):
    milestone = ProjectMilestone.objects.select_for_update().select_related('project', 'project__project_type').get(pk=milestone.pk)
    if not can_submit_project_milestone(actor, milestone):
        raise PermissionDenied
    previous = milestone.latest_submission
    if previous and (not hasattr(previous, 'review') or previous.review.outcome != 'REVISION_REQUIRED'):
        raise ValidationError('Bu aşama yeni teslim kabul etmiyor.')
    if len(files) > 10:
        raise ValidationError('En fazla 10 dosya eklenebilir.')
    if len(links) > 20:
        raise ValidationError('En fazla 20 bağlantı eklenebilir.')
    for url in links:
        validate_public_website(url)
    for upload in files:
        if upload.size <= 0 or upload.size > 20 * 1024 * 1024:
            raise ValidationError('Dosyalar 20 MB sınırında olmalıdır.')
        validate_project_upload_content(upload)
    submission = ProjectMilestoneSubmission.objects.create(
        milestone=milestone, submitted_by=actor, attempt_number=(previous.attempt_number + 1 if previous else 1),
        completion_note=note,
    )
    submission._accepting_evidence = True
    try:
        for url in links:
            ProjectMilestoneSubmissionLink.objects.create(submission=submission, url=url)
        for upload in files:
            item = ProjectMilestoneSubmissionFile(submission=submission, file=upload)
            try:
                item.save()
            finally:
                if item.file and item.file._committed:
                    saved_files.append((item.file.storage, item.file.name))
        record_audit_event(actor=actor, action='project.milestone.submitted', target=submission,
                           metadata={'milestone_id': milestone.pk, 'attempt': submission.attempt_number})
        project = milestone.project
        instructors = [item.instructor for item in CourseInstructor.objects.filter(
            course_id=project.course_id, is_active=True, instructor__profile__user_type='teacher'
        ).select_related('instructor')] if project.course_id else []
        _notify([project.advisor, *instructors], actor=actor,
                message=f'{project.title}: {milestone.title} aşaması teslim edildi.',
                url=f'{project.get_absolute_url()}#milestone-{milestone.pk}', key=f'milestone-submission-{submission.pk}')
        submission._accepting_evidence = False
        return submission
    except Exception:
        submission._accepting_evidence = False
        raise


@transaction.atomic
def review_milestone(*, submission, actor, outcome, score=None, feedback=''):
    milestone = ProjectMilestone.objects.select_for_update().select_related('project', 'project__project_type').get(pk=submission.milestone_id)
    submission = ProjectMilestoneSubmission.objects.select_for_update().get(pk=submission.pk, milestone=milestone)
    if not can_review_project_milestone(actor, milestone):
        raise PermissionDenied
    if milestone.latest_submission.pk != submission.pk or hasattr(submission, 'review'):
        raise ValidationError('Bu teslim artık değerlendirilemez.')
    review = ProjectMilestoneReview(submission=submission, reviewed_by=actor,
                                    outcome=outcome, score=score, feedback=feedback)
    review.save()
    record_audit_event(actor=actor, action='project.milestone.reviewed', target=review,
                       metadata={'milestone_id': milestone.pk, 'outcome': outcome})
    project = milestone.project
    _notify([project.created_by, *project.team.all()], actor=actor,
            message=f'{project.title}: {milestone.title} değerlendirmesi tamamlandı.',
            url=f'{project.get_absolute_url()}#milestone-{milestone.pk}', key=f'milestone-review-{review.pk}')
    return review
