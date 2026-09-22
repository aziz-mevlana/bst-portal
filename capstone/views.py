import logging
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.policies import role_of

from .forms import CapstoneReviewForm, CapstoneStartForm, CapstoneTaskForm
from .models import (
    CapstoneCheckpoint,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneTask,
    CapstoneTerm,
)
from .policies import (
    can_administer_capstone,
    can_review_capstone,
    can_view_capstone,
    is_capstone_eligible_student,
)
from .services import (
    create_capstone_project,
    create_capstone_submission,
    review_capstone_submission,
)
from .workflow import (
    CheckpointProgress,
    TaskWorkflowState,
    get_checkpoint_progress,
    get_task_workflow_state,
    is_checkpoint_overdue,
    is_task_overdue,
    latest_submission_attempt,
)


logger = logging.getLogger(__name__)


TASK_STATE_LABELS = {
    TaskWorkflowState.NOT_SUBMITTED: 'Teslim edilmedi',
    TaskWorkflowState.AWAITING_REVIEW: 'Değerlendirme bekliyor',
    TaskWorkflowState.REVISION_REQUIRED: 'Revizyon gerekli',
    TaskWorkflowState.REJECTED: 'Reddedildi',
    TaskWorkflowState.ACCEPTED: 'Kabul edildi',
}
TASK_STATE_STYLES = {
    TaskWorkflowState.NOT_SUBMITTED: 'bg-slate-100 text-slate-700',
    TaskWorkflowState.AWAITING_REVIEW: 'bg-amber-100 text-amber-800',
    TaskWorkflowState.REVISION_REQUIRED: 'bg-orange-100 text-orange-800',
    TaskWorkflowState.REJECTED: 'bg-red-100 text-red-800',
    TaskWorkflowState.ACCEPTED: 'bg-emerald-100 text-emerald-800',
}
CHECKPOINT_LABELS = {
    CheckpointProgress.NOT_STARTED: 'Başlanmadı',
    CheckpointProgress.IN_PROGRESS: 'Devam ediyor',
    CheckpointProgress.COMPLETED: 'Tamamlandı',
}
SUBMITTABLE_STATES = {
    TaskWorkflowState.NOT_SUBMITTED,
    TaskWorkflowState.REVISION_REQUIRED,
    TaskWorkflowState.REJECTED,
}


def _active_term():
    return CapstoneTerm.objects.filter(is_active=True).first()


def _student_dashboard_project(user, term):
    return (
        _capstone_projects_with_workflow()
        .filter(term=term, project__created_by=user)
        .exclude(project__development_status='cancelled')
        .first()
    )


def _capstone_projects_with_workflow():
    attempt_queryset = (
        CapstoneSubmissionAttempt.objects.select_related(
            'submitted_by',
            'review',
            'review__reviewed_by',
        )
        .prefetch_related('files')
        .order_by('attempt_number', 'pk')
    )
    task_queryset = (
        CapstoneTask.objects.select_related('created_by').prefetch_related(
            Prefetch('submission_attempts', queryset=attempt_queryset)
        )
        .order_by('due_at', 'pk')
    )
    checkpoint_queryset = (
        CapstoneCheckpoint.objects.prefetch_related(
            Prefetch('tasks', queryset=task_queryset)
        )
        .order_by('due_at', 'kind')
    )
    return CapstoneProject.objects.select_related(
        'project__advisor',
        'project__created_by',
        'project__created_by__profile',
        'term',
    ).prefetch_related(
        Prefetch('checkpoints', queryset=checkpoint_queryset)
    )


def _prepare_dashboard(capstone_project):
    checkpoints = list(capstone_project.checkpoints.all())
    for checkpoint in checkpoints:
        tasks = list(checkpoint.tasks.all())
        for task in tasks:
            state = get_task_workflow_state(task)
            task.dashboard_state = state
            task.dashboard_state_label = TASK_STATE_LABELS[state]
            task.dashboard_state_style = TASK_STATE_STYLES[state]
            task.dashboard_is_overdue = is_task_overdue(task)
            task.dashboard_can_submit = state in SUBMITTABLE_STATES
            task.dashboard_attempts = list(task.submission_attempts.all())
        progress = get_checkpoint_progress(checkpoint)
        checkpoint.dashboard_progress = progress
        checkpoint.dashboard_progress_label = CHECKPOINT_LABELS[progress]
        checkpoint.dashboard_is_overdue = is_checkpoint_overdue(checkpoint)
        checkpoint.dashboard_tasks = tasks
    return checkpoints


def _validation_messages(error):
    if hasattr(error, 'message_dict'):
        return [message for values in error.message_dict.values() for message in values]
    return error.messages


def _add_validation_error(form, error):
    if hasattr(error, 'message_dict'):
        for field, field_messages in error.message_dict.items():
            target = field if field in form.fields else None
            for message in field_messages:
                form.add_error(target, message)
        return
    for message in error.messages:
        form.add_error(None, message)


def _is_advisor_workspace_user(user):
    return bool(
        getattr(user, 'is_authenticated', False)
        and user.is_active
        and not user.is_staff
        and not user.is_superuser
        and role_of(user) == 'teacher'
    )


def _advisor_access_or_404(user):
    if not _is_advisor_workspace_user(user):
        raise Http404


def _prepare_advisor_project(
    capstone_project,
    *,
    task_form=None,
    task_checkpoint_id=None,
    review_form=None,
    review_attempt_id=None,
):
    checkpoints = _prepare_dashboard(capstone_project)
    pending_review_count = 0
    overdue_task_count = 0
    completed_checkpoint_count = 0

    for checkpoint in checkpoints:
        checkpoint.advisor_task_error_form = None
        if checkpoint.dashboard_progress == CheckpointProgress.COMPLETED:
            completed_checkpoint_count += 1
            if checkpoint.pk == task_checkpoint_id and task_form is not None:
                checkpoint.advisor_task_error_form = task_form
            checkpoint.advisor_task_form = None
        else:
            checkpoint.advisor_task_form = (
                task_form
                if checkpoint.pk == task_checkpoint_id and task_form is not None
                else CapstoneTaskForm(auto_id=f'id_checkpoint_{checkpoint.pk}_%s')
            )

        for task in checkpoint.dashboard_tasks:
            if task.dashboard_is_overdue:
                overdue_task_count += 1
            latest_attempt = latest_submission_attempt(task)
            for attempt in task.dashboard_attempts:
                attempt.advisor_review_error_form = None
                if (
                    attempt.pk == review_attempt_id
                    and review_form is not None
                    and not (
                        attempt is latest_attempt
                        and task.dashboard_state == TaskWorkflowState.AWAITING_REVIEW
                    )
                ):
                    attempt.advisor_review_error_form = review_form
            if task.dashboard_state == TaskWorkflowState.AWAITING_REVIEW:
                pending_review_count += 1
                if latest_attempt is not None:
                    latest_attempt.advisor_review_form = (
                        review_form
                        if latest_attempt.pk == review_attempt_id and review_form is not None
                        else CapstoneReviewForm(
                            auto_id=f'id_attempt_{latest_attempt.pk}_%s'
                        )
                    )

    capstone_project.advisor_checkpoints = checkpoints
    capstone_project.completed_checkpoint_count = completed_checkpoint_count
    capstone_project.total_checkpoint_count = len(checkpoints)
    capstone_project.pending_review_count = pending_review_count
    capstone_project.overdue_task_count = overdue_task_count
    return capstone_project


def _advisor_project_or_404(user, project_id):
    return get_object_or_404(
        _capstone_projects_with_workflow(),
        pk=project_id,
        project__advisor=user,
    )


def _render_advisor_project(
    request,
    capstone_project,
    *,
    task_form=None,
    task_checkpoint_id=None,
    review_form=None,
    review_attempt_id=None,
):
    _prepare_advisor_project(
        capstone_project,
        task_form=task_form,
        task_checkpoint_id=task_checkpoint_id,
        review_form=review_form,
        review_attempt_id=review_attempt_id,
    )
    return render(request, 'capstone/advisor_project_detail.html', {
        'capstone_project': capstone_project,
        'checkpoints': capstone_project.advisor_checkpoints,
    })


@login_required
@require_GET
def student_home(request):
    term = _active_term()
    capstone_project = _student_dashboard_project(request.user, term) if term else None
    if capstone_project is not None:
        return render(request, 'capstone/student_home.html', {
            'term': term,
            'capstone_project': capstone_project,
            'checkpoints': _prepare_dashboard(capstone_project),
        })

    eligible = bool(term and is_capstone_eligible_student(request.user, term))
    return render(request, 'capstone/student_home.html', {
        'term': term,
        'eligible': eligible,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def student_start(request):
    term = _active_term()
    if term is None or not is_capstone_eligible_student(request.user, term):
        messages.info(request, 'Bu dönem için aktif bitirme projesi kaydınız bulunmuyor.')
        return redirect('capstone:student_home')
    if _student_dashboard_project(request.user, term) is not None:
        messages.info(request, 'Bu dönem için bitirme projeniz zaten bulunuyor.')
        return redirect('capstone:student_home')

    form = CapstoneStartForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            create_capstone_project(
                student=request.user,
                advisor=form.cleaned_data['advisor'],
                title=form.cleaned_data['title'],
                description=form.cleaned_data['description'],
                term=term,
            )
        except ValidationError as error:
            for message in _validation_messages(error):
                form.add_error(None, message)
        else:
            messages.success(request, 'Bitirme projeniz başarıyla başlatıldı.')
            return redirect('capstone:student_home')

    return render(request, 'capstone/student_start.html', {'form': form, 'term': term})


@login_required
@require_POST
def student_task_submit(request, task_id):
    task_queryset = CapstoneTask.objects.select_related(
        'capstone_project__project',
        'capstone_project__term',
    ).exclude(capstone_project__project__development_status='cancelled')
    task = get_object_or_404(
        task_queryset,
        pk=task_id,
        capstone_project__project__created_by=request.user,
        capstone_project__term__is_active=True,
    )
    anchor_url = f"{reverse('capstone:student_home')}#task-{task.pk}"
    try:
        create_capstone_submission(
            task=task,
            student=request.user,
            files=request.FILES.getlist('files'),
        )
    except ValidationError as error:
        messages.error(request, ' '.join(_validation_messages(error)))
    else:
        messages.success(request, 'Tesliminiz başarıyla kaydedildi.')
    return redirect(anchor_url)


@login_required
@require_GET
def advisor_home(request):
    _advisor_access_or_404(request.user)
    projects = list(
        _capstone_projects_with_workflow()
        .filter(project__advisor=request.user)
        .order_by('-term__academic_year', 'term__semester', 'project__title')
    )
    for capstone_project in projects:
        _prepare_advisor_project(capstone_project)
    return render(request, 'capstone/advisor_home.html', {'capstone_projects': projects})


@login_required
@require_GET
def advisor_project_detail(request, project_id):
    _advisor_access_or_404(request.user)
    return _render_advisor_project(
        request,
        _advisor_project_or_404(request.user, project_id),
    )


@login_required
@require_POST
def advisor_task_create(request, checkpoint_id):
    _advisor_access_or_404(request.user)
    checkpoint = get_object_or_404(
        CapstoneCheckpoint.objects.select_related('capstone_project__project'),
        pk=checkpoint_id,
        capstone_project__project__advisor=request.user,
    )
    form = CapstoneTaskForm(request.POST)
    if get_checkpoint_progress(checkpoint) == CheckpointProgress.COMPLETED:
        form.add_error(None, 'Tamamlanmış kontrol noktasına yeni görev eklenemez.')
    elif form.is_valid():
        task = form.save(commit=False)
        task.capstone_project = checkpoint.capstone_project
        task.checkpoint = checkpoint
        task.created_by = request.user
        try:
            task.save()
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, 'Görev başarıyla oluşturuldu.')
            detail_url = reverse(
                'capstone:advisor_project_detail',
                args=[checkpoint.capstone_project_id],
            )
            return redirect(f'{detail_url}#task-{task.pk}')

    capstone_project = _advisor_project_or_404(
        request.user,
        checkpoint.capstone_project_id,
    )
    return _render_advisor_project(
        request,
        capstone_project,
        task_form=form,
        task_checkpoint_id=checkpoint.pk,
    )


@login_required
@require_POST
def advisor_submission_review(request, attempt_id):
    _advisor_access_or_404(request.user)
    attempt = get_object_or_404(
        CapstoneSubmissionAttempt.objects.select_related(
            'task__capstone_project__project'
        ),
        pk=attempt_id,
        task__capstone_project__project__advisor=request.user,
    )
    form = CapstoneReviewForm(request.POST)
    if form.is_valid():
        try:
            review_capstone_submission(
                submission_attempt=attempt,
                reviewer=request.user,
                decision=form.cleaned_data['decision'],
                feedback=form.cleaned_data['feedback'],
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, 'Teslim değerlendirmesi kaydedildi.')
            detail_url = reverse(
                'capstone:advisor_project_detail',
                args=[attempt.task.capstone_project_id],
            )
            return redirect(f'{detail_url}#task-{attempt.task_id}')

    capstone_project = _advisor_project_or_404(
        request.user,
        attempt.task.capstone_project_id,
    )
    return _render_advisor_project(
        request,
        capstone_project,
        review_form=form,
        review_attempt_id=attempt.pk,
    )


def _can_download_submission_file(user, capstone_project):
    if not can_view_capstone(user, capstone_project):
        return False
    project = capstone_project.project
    return bool(
        user.pk == project.created_by_id
        or can_review_capstone(user, capstone_project)
        or can_administer_capstone(user, capstone_project)
    )


def _safe_download_filename(original_name):
    filename = str(original_name or '').replace('\r', '').replace('\n', '').strip()
    return filename or 'capstone-submission-file'


@require_GET
def submission_file_download(request, file_id):
    submission_file = get_object_or_404(
        CapstoneSubmissionFile.objects.select_related(
            'submission_attempt__task__capstone_project__project',
        ),
        pk=file_id,
    )
    capstone_project = submission_file.submission_attempt.task.capstone_project
    if not _can_download_submission_file(request.user, capstone_project):
        raise Http404

    if not submission_file.file:
        raise Http404
    try:
        if not submission_file.file.storage.exists(submission_file.file.name):
            logger.warning('CAPSTONE teslim dosyası storage üzerinde bulunamadı: id=%s', file_id)
            raise Http404
        file_handle = submission_file.file.open('rb')
    except Http404:
        raise
    except Exception:
        logger.warning(
            'CAPSTONE teslim dosyası storage üzerinden açılamadı: id=%s',
            file_id,
            exc_info=True,
        )
        raise Http404 from None

    filename = _safe_download_filename(submission_file.original_name)
    content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response
