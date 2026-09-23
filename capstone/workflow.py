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


CAPSTONE_STAGES = ('Fikir', 'Planlama', 'Geliştiriliyor', 'Test / Son Kontroller', 'Tamamlandı')
OFFICIAL_CHECKPOINT_KINDS = ('FIRST_REVIEW', 'MIDTERM_REVIEW', 'POST_MIDTERM_REVIEW', 'FINAL_REVIEW')


def capstone_overview(capstone_project, now=None):
    """One derived academic snapshot shared by student and advisor screens."""
    current_time = now or timezone.now()
    checkpoints = list(capstone_project.checkpoints.all())
    by_kind = {checkpoint.kind: checkpoint for checkpoint in checkpoints}
    earned = assessed_max = total_max = 0
    completed_checkpoints = 0
    pending_reviews = overdue_tasks = accepted_tasks = task_count = 0
    ready_evaluations = []
    deadlines = []
    next_action = None
    any_activity = False

    for checkpoint in checkpoints:
        tasks = list(checkpoint.tasks.all())
        evaluation = getattr(checkpoint, 'evaluation', None)
        checkpoint.dashboard_evaluation = evaluation
        checkpoint.dashboard_accepted_count = sum(
            get_task_workflow_state(task) == TaskWorkflowState.ACCEPTED for task in tasks
        )
        checkpoint.dashboard_task_count = len(tasks)
        task_count += len(tasks)
        accepted_tasks += checkpoint.dashboard_accepted_count
        total_max += checkpoint.max_score
        if evaluation:
            earned += evaluation.score
            assessed_max += checkpoint.max_score
        if tasks and checkpoint.dashboard_accepted_count == len(tasks):
            completed_checkpoints += 1
        if tasks or evaluation:
            any_activity = True
        if tasks and checkpoint.dashboard_accepted_count == len(tasks) and not evaluation:
            ready_evaluations.append(checkpoint)
        if not tasks or checkpoint.dashboard_accepted_count != len(tasks):
            deadlines.append(checkpoint.due_at)
        for task in tasks:
            state = get_task_workflow_state(task)
            if state == TaskWorkflowState.AWAITING_REVIEW:
                pending_reviews += 1
            if is_task_overdue(task, current_time):
                overdue_tasks += 1
            if state != TaskWorkflowState.ACCEPTED:
                deadlines.append(task.due_at)
            if next_action is None and state in {TaskWorkflowState.REVISION_REQUIRED, TaskWorkflowState.REJECTED}:
                next_action = {'text': f'{task.title}: danışman geri bildirimine göre yeni teslim yapın.', 'task_id': task.pk}

    if next_action is None and pending_reviews:
        next_action = {'text': 'Tesliminiz danışman değerlendirmesi bekliyor.'}
    if next_action is None and ready_evaluations:
        next_action = {'text': 'Tamamlanan kontrol noktaları danışmanınız tarafından izleniyor.'}
    if next_action is None:
        for checkpoint in checkpoints:
            for task in checkpoint.tasks.all():
                if get_task_workflow_state(task) == TaskWorkflowState.NOT_SUBMITTED:
                    next_action = {'text': f'{task.title}: ilk tesliminizi yapın.', 'task_id': task.pk}
                    break
            if next_action:
                break
    if next_action is None:
        next_action = {'text': 'Danışmanınızın sıradaki görev tanımını bekleyin.'}

    completed = bool(capstone_project.completed_at or capstone_project.project.development_status == 'completed')
    ready = len(by_kind) == 4 and all(
        checkpoint.kind in OFFICIAL_CHECKPOINT_KINDS
        and checkpoint.dashboard_task_count > 0
        and checkpoint.dashboard_accepted_count == checkpoint.dashboard_task_count
        for checkpoint in checkpoints
    )
    if completed:
        stage_index = 4
        next_action = {'text': 'Bitirme projeniz tamamlandı. Proje vitrininizi tamamlayın.'}
    elif by_kind.get('POST_MIDTERM_REVIEW') and get_checkpoint_progress(by_kind['POST_MIDTERM_REVIEW']) == CheckpointProgress.COMPLETED:
        stage_index = 3
    elif by_kind.get('FIRST_REVIEW') and get_checkpoint_progress(by_kind['FIRST_REVIEW']) == CheckpointProgress.COMPLETED:
        stage_index = 2
    elif any_activity:
        stage_index = 1
    else:
        stage_index = 0
    if ready and not completed:
        next_action = {'text': 'Tüm akademik şartlar tamamlandı; danışmanınızın projeyi tamamlamasını bekleyin.'}
    return {
        'stage': CAPSTONE_STAGES[stage_index],
        'stage_index': stage_index,
        'timeline': [{'label': label, 'state': 'complete' if index < stage_index else 'current' if index == stage_index else 'upcoming'}
                     for index, label in enumerate(CAPSTONE_STAGES)],
        'progress_percent': 100 if completed else round(100 * completed_checkpoints / len(checkpoints)) if checkpoints else 0,
        'score_earned': earned,
        'score_assessed_max': assessed_max,
        'score_total_max': total_max,
        'pending_review_count': pending_reviews,
        'overdue_task_count': overdue_tasks,
        'task_count': task_count,
        'accepted_task_count': accepted_tasks,
        'next_deadline': min(deadlines) if deadlines and not completed else None,
        'next_action': next_action,
        'ready_evaluations': ready_evaluations,
        'completion_ready': ready and not completed,
        'completed': completed,
    }
