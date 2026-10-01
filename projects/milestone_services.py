from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from core.audit import record_audit_event
from core.notifications import create_notification
from accounts.validators import validate_public_website
from .models import (
    CourseInstructor, ProjectMilestone, ProjectMilestoneReview,
    ProjectMilestoneSubmission, ProjectMilestoneSubmissionFile,
    ProjectMilestoneSubmissionLink, ProjectMilestoneSubmissionReference, validate_project_upload_content,
)
from .course_work_services import lock_assignment_for_project
from .milestone_policies import can_manage_project_milestones, can_submit_project_milestone, can_review_project_milestone


def _locked_milestone(pk, **filters):
    milestone = ProjectMilestone.objects.select_for_update(of=("self",)).select_related("project", "project__project_type").filter(pk=pk, **filters).first()
    if milestone is None:
        raise ValidationError("Kontrol noktası artık mevcut değil.")
    return milestone


def _notify(users, *, actor, message, url, key):
    for user in {user.pk: user for user in users if user}.values():
        create_notification(recipient=user, actor=actor, notification_type='project_milestone',
                            message=message, target_url=url, dedupe_key=key)


@transaction.atomic
def save_milestone(*, project, actor, values, milestone=None):
    lock_assignment_for_project(project.pk)
    project = type(project).objects.select_for_update().select_related('project_type').get(pk=project.pk)
    if not can_manage_project_milestones(actor, project):
        raise PermissionDenied
    if milestone:
        milestone = _locked_milestone(milestone.pk, project=project)
        if milestone.assignment_checkpoint_id:
            raise ValidationError('Ortak kontrol noktası çalışma planından düzenlenir.')
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
    project_id = ProjectMilestone.objects.filter(pk=milestone.pk).values_list('project_id', flat=True).first()
    if project_id is None:
        raise ValidationError('Kontrol noktası artık mevcut değil.')
    lock_assignment_for_project(project_id)
    milestone = _locked_milestone(milestone.pk)
    if not can_manage_project_milestones(actor, milestone.project):
        raise PermissionDenied
    if milestone.assignment_checkpoint_id:
        raise ValidationError('Ortak kontrol noktası çalışma planından yönetilir.')
    if milestone.submissions.exists():
        raise ValidationError('Teslim veya değerlendirme geçmişi bulunan proje aşaması silinemez.')
    project_id, milestone_id = milestone.project_id, milestone.pk
    record_audit_event(actor=actor, action='project.milestone.deleted', target=milestone,
                       metadata={'project_id': project_id, 'milestone_id': milestone_id})
    milestone.delete()


def submit_milestone(*, milestone, actor, note='', links=(), files=(), references=()):
    saved_files = []
    try:
        return _submit_milestone_atomic(milestone=milestone, actor=actor, note=note,
                                        links=links, files=files, references=references, saved_files=saved_files)
    except Exception:
        for storage, name in saved_files:
            try:
                storage.delete(name)
            except OSError:
                pass
        raise


@transaction.atomic
def _submit_milestone_atomic(*, milestone, actor, note, links, files, references, saved_files):
    project_id = ProjectMilestone.objects.filter(pk=milestone.pk).values_list('project_id', flat=True).first()
    if project_id is None:
        raise ValidationError('Kontrol noktası artık mevcut değil.')
    lock_assignment_for_project(project_id)
    milestone = _locked_milestone(milestone.pk)
    if not can_submit_project_milestone(actor, milestone):
        raise PermissionDenied
    previous = milestone.latest_submission
    if previous and (not hasattr(previous, 'review') or previous.review.outcome != 'REVISION_REQUIRED'):
        raise ValidationError('Bu aşama yeni teslim kabul etmiyor.')
    requirements = {}
    if milestone.assignment_checkpoint_id:
        from .course_requirements import validate_evidence
        requirements = deepcopy(milestone.assignment_checkpoint.evidence_requirements)
        validate_evidence(requirements, files=files, links=links, references=references, note=note)
    elif references:
        raise ValidationError('Kaynakça bu çalışma türünde kullanılmıyor.')
    if len(references) > 100:
        raise ValidationError('En fazla 100 kaynak eklenebilir.')
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {'title', 'url'}:
            raise ValidationError('Geçersiz kaynak.')
        item = ProjectMilestoneSubmissionReference(**reference)
        item.clean()
        if len(item.title) > 500 or len(item.url) > 500:
            raise ValidationError('Kaynak başlığı veya URL çok uzun.')
    if milestone.assignment_checkpoint_id and len(note) > 20000:
        raise ValidationError('Metin en fazla 20000 karakter olabilir.')
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
        completion_note=note, requirement_snapshot=requirements,
    )
    submission._accepting_evidence = True
    try:
        for reference in references:
            ProjectMilestoneSubmissionReference.objects.create(submission=submission, **reference)
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
        work = getattr(project, 'course_project_work', None)
        instructors = ([work.assignment.instructor] if work else [item.instructor for item in CourseInstructor.objects.filter(
            course_id=project.course_id, is_active=True, instructor__profile__user_type='teacher'
        ).select_related('instructor')] if project.course_id else [])
        target_url = (reverse('projects:course_work_detail', args=[work.pk]) if work else project.get_absolute_url())
        _notify([project.advisor, *instructors], actor=actor,
                message=f'{project.title}: {milestone.effective_title} aşaması teslim edildi.',
                url=f'{target_url}#checkpoint-{milestone.pk}' if work else f'{target_url}#milestone-{milestone.pk}',
                key=f'milestone-submission-{submission.pk}')
        submission._accepting_evidence = False
        return submission
    except Exception:
        submission._accepting_evidence = False
        raise


@transaction.atomic
def review_milestone(*, submission, actor, outcome, score=None, feedback='', private_note='', private_score=None):
    project_id = ProjectMilestone.objects.filter(pk=submission.milestone_id).values_list('project_id', flat=True).first()
    if project_id is None:
        raise ValidationError('Kontrol noktası artık mevcut değil.')
    lock_assignment_for_project(project_id)
    milestone = _locked_milestone(submission.milestone_id)
    submission = ProjectMilestoneSubmission.objects.select_for_update().get(pk=submission.pk, milestone=milestone)
    if not can_review_project_milestone(actor, milestone):
        raise PermissionDenied
    if milestone.latest_submission.pk != submission.pk or hasattr(submission, 'review'):
        raise ValidationError('Bu teslim artık değerlendirilemez.')
    if milestone.assignment_checkpoint_id and score is not None:
        raise ValidationError('Ders projesinde puan yalnız özel değerlendirmede tutulur.')
    if not milestone.assignment_checkpoint_id and (private_note or private_score is not None):
        raise ValidationError('Özel değerlendirme yalnız Ders Projesi içindir.')
    review = ProjectMilestoneReview(submission=submission, reviewed_by=actor,
                                    outcome=outcome, score=score, feedback=feedback)
    review.save()
    if milestone.assignment_checkpoint_id:
        from .course_work_models import CoursePrivateEvaluation
        CoursePrivateEvaluation.objects.create(review=review, actor=actor, note=private_note, score=private_score)
    record_audit_event(actor=actor, action='project.milestone.reviewed', target=review,
                       metadata={'milestone_id': milestone.pk, 'outcome': outcome})
    project = milestone.project
    work = getattr(project, 'course_project_work', None)
    target_url = (reverse('projects:course_work_detail', args=[work.pk]) if work else project.get_absolute_url())
    _notify([project.created_by, *project.team.all()], actor=actor,
            message=f'{project.title}: {milestone.effective_title} değerlendirmesi tamamlandı.',
            url=f'{target_url}#checkpoint-{milestone.pk}' if work else f'{target_url}#milestone-{milestone.pk}',
            key=f'milestone-review-{review.pk}')
    return review


@transaction.atomic
def update_private_evaluation(*, review, actor, note, score, expected_id):
    from .course_work_models import CoursePrivateEvaluation
    lock_assignment_for_project(review.submission.milestone.project_id)
    review = ProjectMilestoneReview.objects.select_for_update(of=('self',)).select_related('submission__milestone__assignment_checkpoint').get(pk=review.pk)
    if not can_review_project_milestone(actor, review.submission.milestone):
        raise PermissionDenied
    previous = review.private_evaluations.order_by('-pk').first()
    if (previous.pk if previous else 0) != expected_id:
        raise ValidationError('Özel değerlendirme değişti. Sayfayı yenileyin.')
    result = CoursePrivateEvaluation.objects.create(review=review, actor=actor, note=note, score=score)
    record_audit_event(actor=actor, action='course.private_evaluation_updated', target=review)
    return result
