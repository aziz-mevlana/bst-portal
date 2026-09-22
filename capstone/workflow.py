from enum import StrEnum

from django.utils import timezone

from .models import CapstoneSubmissionAttempt, CapstoneSubmissionReview


class TaskWorkflowState(StrEnum):
    NOT_SUBMITTED = 'NOT_SUBMITTED'
    AWAITING_REVIEW = 'AWAITING_REVIEW'
    REVISION_REQUIRED = 'REVISION_REQUIRED'
    REJECTED = 'REJECTED'
    ACCEPTED = 'ACCEPTED'


class CheckpointProgress(StrEnum):
    NOT_STARTED = 'NOT_STARTED'
    IN_PROGRESS = 'IN_PROGRESS'
    COMPLETED = 'COMPLETED'


def latest_submission_attempt(task):
    if task is None or getattr(task, 'pk', None) is None:
        return None
    prefetched_attempts = getattr(task, '_prefetched_objects_cache', {}).get(
        'submission_attempts'
    )
    if prefetched_attempts is not None:
        return max(
            prefetched_attempts,
            key=lambda attempt: (attempt.attempt_number, attempt.pk),
            default=None,
        )
    return (
        CapstoneSubmissionAttempt.objects.filter(task_id=task.pk)
        .order_by('-attempt_number', '-pk')
        .first()
    )


def get_task_workflow_state(task):
    latest_attempt = latest_submission_attempt(task)
    if latest_attempt is None:
        return TaskWorkflowState.NOT_SUBMITTED

    try:
        review = latest_attempt.review
    except CapstoneSubmissionReview.DoesNotExist:
        review = None
    decision = review.decision if review is not None else None
    if decision is None:
        return TaskWorkflowState.AWAITING_REVIEW
    return TaskWorkflowState(decision)


def _aware(value):
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def is_task_overdue(task, now=None):
    if get_task_workflow_state(task) == TaskWorkflowState.ACCEPTED:
        return False
    current_time = _aware(now or timezone.now())
    return current_time > _aware(task.due_at)


def get_checkpoint_progress(checkpoint):
    tasks = list(checkpoint.tasks.all())
    if not tasks:
        return CheckpointProgress.NOT_STARTED
    if all(get_task_workflow_state(task) == TaskWorkflowState.ACCEPTED for task in tasks):
        return CheckpointProgress.COMPLETED
    return CheckpointProgress.IN_PROGRESS


def is_checkpoint_overdue(checkpoint, now=None):
    if get_checkpoint_progress(checkpoint) == CheckpointProgress.COMPLETED:
        return False
    current_time = _aware(now or timezone.now())
    return current_time > _aware(checkpoint.due_at)
