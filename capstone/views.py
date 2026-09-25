import logging
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.policies import is_admin, role_of

from .forms import CapstoneEvaluationForm, CapstoneProposalRejectForm, CapstoneReviewForm, CapstoneStartForm, CapstoneTaskForm
from .models import (
    CapstoneCheckpoint,
    CapstoneCheckpointEvaluation,
    CapstoneEnrollment,
    CapstoneProposal,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneTask,
    CapstoneTerm,
)
from .policies import (
    can_administer_capstone,
    can_review_capstone,
    can_review_capstone_proposal,
    can_view_capstone,
    is_capstone_eligible_student,
)
from .academic_services import academic_overview, initialize_project
from .academic_views import workspace_context
from .services import (
    create_capstone_task,
    create_capstone_submission,
    complete_capstone_project,
    approve_capstone_proposal,
    evaluate_capstone_checkpoint,
    reject_capstone_proposal,
    review_capstone_submission,
    submit_capstone_proposal,
    withdraw_capstone_proposal,
)
from .workflow import (
    CheckpointProgress,
    TaskWorkflowState,
    capstone_overview,
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
    projects = _capstone_projects_with_workflow().filter(project__created_by=user).exclude(
        project__development_status='cancelled'
    )
    current = projects.filter(term=term).first() if term else None
    if current:
        return current
    return projects.exclude(project__development_status='completed').order_by('-term__academic_year', '-created_at').first()


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
        CapstoneCheckpoint.objects.select_related('evaluation', 'evaluation__evaluated_by').prefetch_related(
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
    capstone_project.overview = capstone_overview(capstone_project)
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
    if not (_is_advisor_workspace_user(user) or is_admin(user)):
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
    if not checkpoints:
        academic = academic_overview(capstone_project)
        capstone_project.overview = {
            'stage': 'Tamamlandı' if academic['completed'] else 'Geliştiriliyor' if academic['approved'] else 'Planlama',
            'progress_percent': academic['percent'], 'pending_review_count': academic['pending'],
            'overdue_task_count': academic['overdue'], 'completion_ready': academic['completion_ready'],
            'next_deadline': academic['next_due'], 'ready_evaluations': (), 'completed': academic['completed'],
        }
        capstone_project.advisor_checkpoints = []
        capstone_project.completed_checkpoint_count = academic['approved']
        capstone_project.total_checkpoint_count = academic['total']
        capstone_project.pending_review_count = academic['pending']
        capstone_project.overdue_task_count = academic['overdue']
        return capstone_project
    pending_review_count = 0
    overdue_task_count = 0
    completed_checkpoint_count = 0

    for checkpoint in checkpoints:
        checkpoint.advisor_task_error_form = None
        checkpoint.advisor_evaluation_form = (
            CapstoneEvaluationForm(auto_id=f'id_evaluation_{checkpoint.pk}_%s')
            if checkpoint in capstone_project.overview['ready_evaluations'] else None
        )
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
    queryset = _capstone_projects_with_workflow()
    if not is_admin(user):
        queryset = queryset.filter(project__advisor=user)
    return get_object_or_404(queryset, pk=project_id)


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
        'overview': capstone_project.overview,
    })


@login_required
@require_GET
def student_home(request):
    term = _active_term()
    capstone_project = _student_dashboard_project(request.user, term)
    if capstone_project is not None:
        if not capstone_project.checkpoints.exists():
            return render(request, 'capstone/academic_workspace.html', workspace_context(capstone_project, request.user))
        checkpoints = _prepare_dashboard(capstone_project)
        return render(request, 'capstone/student_home.html', {
            'term': capstone_project.term,
            'capstone_project': capstone_project,
            'checkpoints': checkpoints,
            'overview': capstone_project.overview,
        })

    enrollment = CapstoneEnrollment.objects.select_related('advisor').filter(
        term=term, student=request.user, is_active=True
    ).first() if term else None
    return render(request, 'capstone/student_home.html', {
        'term': term,
        'enrollment': enrollment,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def student_start(request):
    term = _active_term()
    if term is None or not is_capstone_eligible_student(request.user, term):
        messages.info(request, 'Bu dönem Bitirme Projesi öğrenci listesinde bulunmuyorsunuz.')
        return redirect('capstone:student_home')
    enrollment = get_object_or_404(CapstoneEnrollment.objects.select_related('advisor'), term=term,
                                   student=request.user, is_active=True)
    if not enrollment.advisor_id:
        messages.info(request, 'Danışman ataması bekleniyor.')
        return redirect('capstone:student_home')
    if _student_dashboard_project(request.user, term) is not None:
        messages.info(request, 'Bu dönem için bitirme projeniz zaten bulunuyor.')
        return redirect('capstone:student_home')
    form = CapstoneStartForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            initialize_project(
                enrollment=enrollment,
                student=request.user,
                title=form.cleaned_data['title'],
                description=form.cleaned_data['description'],
            )
        except ValidationError as error:
            for message in _validation_messages(error):
                form.add_error(None, message)
        else:
            messages.success(request, 'Proje bilgileriniz kaydedildi ve çalışma alanınız açıldı.')
            return redirect('capstone:student_home')

    return render(request, 'capstone/student_start.html', {'form': form, 'term': term, 'advisor': enrollment.advisor})


@login_required
@require_POST
def student_proposal_withdraw(request, proposal_id):
    raise Http404


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
    project_queryset = _capstone_projects_with_workflow().exclude(project__development_status='cancelled')
    proposal_queryset = CapstoneProposal.objects.filter(status=CapstoneProposal.Status.PENDING).select_related('student', 'student__profile', 'term', 'requested_advisor')
    if not is_admin(request.user):
        project_queryset = project_queryset.filter(project__advisor=request.user)
        proposal_queryset = proposal_queryset.filter(requested_advisor=request.user)
    selected_term = request.GET.get('term', '')
    if selected_term.isdigit():
        project_queryset = project_queryset.filter(term_id=selected_term)
        proposal_queryset = proposal_queryset.filter(term_id=selected_term)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        project_queryset = project_queryset.filter(Q(project__title__icontains=query) | Q(project__created_by__username__icontains=query) |
                                                   Q(project__created_by__first_name__icontains=query) | Q(project__created_by__last_name__icontains=query))
    projects = list(project_queryset.order_by('-term__academic_year', 'term__semester', 'project__title'))
    for capstone_project in projects:
        _prepare_advisor_project(capstone_project)
    all_projects = projects
    attention_projects = [item for item in all_projects if (
        item.overview['pending_review_count'] or item.overview['ready_evaluations']
        or item.overview['overdue_task_count'] or item.overview['completion_ready']
    )]
    selected_stage = request.GET.get('stage', '')
    if selected_stage in {'Fikir', 'Planlama', 'Geliştiriliyor', 'Test / Son Kontroller', 'Tamamlandı'}:
        projects = [item for item in projects if item.overview['stage'] == selected_stage]
    if request.GET.get('attention') == 'pending':
        projects = [item for item in projects if item.overview['pending_review_count']]
    elif request.GET.get('attention') == 'overdue':
        projects = [item for item in projects if item.overview['overdue_task_count']]
    elif request.GET.get('attention') == 'ready':
        projects = [item for item in projects if item.overview['completion_ready']]
    proposal_count = proposal_queryset.count()
    proposal_page = Paginator(proposal_queryset.order_by('created_at', 'pk'), 20).get_page(request.GET.get('proposal_page'))
    project_page = Paginator(projects, 20).get_page(request.GET.get('page'))
    project_query = request.GET.copy()
    project_query.pop('page', None)
    proposal_query = request.GET.copy()
    proposal_query.pop('proposal_page', None)
    active_term = _active_term()
    academic_totals = list(CapstoneCheckpointEvaluation.objects.filter(
        checkpoint__capstone_project__term=active_term
    ).values('checkpoint__capstone_project_id').annotate(total=Sum('score')).values_list('total', flat=True)) if is_admin(request.user) and active_term else []
    admin_overviews = [capstone_overview(item) for item in _capstone_projects_with_workflow().filter(
        term=active_term
    ).exclude(project__development_status='cancelled')] if is_admin(request.user) and active_term else []
    context = {
        'capstone_projects': project_page, 'project_page': project_page,
        'proposals': proposal_page, 'proposal_page': proposal_page,
        'proposal_count': proposal_count, 'project_page_query': project_query.urlencode(),
        'proposal_page_query': proposal_query.urlencode(), 'reject_form': CapstoneProposalRejectForm(),
        'attention_projects': attention_projects[:10],
        'pending_evaluation_count': sum(len(item.overview['ready_evaluations']) for item in all_projects),
        'terms': CapstoneTerm.objects.all(), 'selected_term': selected_term, 'selected_stage': selected_stage,
        'selected_attention': request.GET.get('attention', ''), 'query': query,
        'active_project_count': sum(not item.overview['completed'] for item in all_projects),
        'pending_review_count': sum(item.overview['pending_review_count'] for item in all_projects),
        'overdue_count': sum(bool(item.overview['overdue_task_count']) for item in all_projects),
        'ready_count': sum(bool(item.overview['completion_ready']) for item in all_projects),
        'active_term': active_term,
        'admin_summary': {
            'enrolled': CapstoneEnrollment.objects.filter(term=active_term, is_active=True).count(),
            'active_projects': CapstoneProject.objects.filter(term=active_term).exclude(project__development_status__in=['cancelled', 'completed']).count(),
            'completed_projects': CapstoneProject.objects.filter(term=active_term, project__development_status='completed').count(),
            'pending_proposals': CapstoneProposal.objects.filter(term=active_term, status=CapstoneProposal.Status.PENDING).count(),
            'pending_reviews': sum(item['pending_review_count'] for item in admin_overviews),
            'overdue_projects': sum(bool(item['overdue_task_count']) for item in admin_overviews),
            'average_score': round(sum(academic_totals) / len(academic_totals), 1) if academic_totals else None,
            'evaluated_projects': len(academic_totals),
        } if is_admin(request.user) and active_term else None,
    }
    return render(request, 'capstone/advisor_home.html', context)


@login_required
@require_GET
def advisor_project_detail(request, project_id):
    _advisor_access_or_404(request.user)
    project = _advisor_project_or_404(request.user, project_id)
    if not project.checkpoints.exists():
        return render(request, 'capstone/academic_workspace_teacher.html', workspace_context(project, request.user))
    return _render_advisor_project(
        request,
        project,
    )


@login_required
@require_POST
def advisor_task_create(request, checkpoint_id):
    _advisor_access_or_404(request.user)
    checkpoint_queryset = CapstoneCheckpoint.objects.select_related('capstone_project__project')
    if not is_admin(request.user):
        checkpoint_queryset = checkpoint_queryset.filter(capstone_project__project__advisor=request.user)
    checkpoint = get_object_or_404(checkpoint_queryset, pk=checkpoint_id)
    form = CapstoneTaskForm(request.POST)
    if get_checkpoint_progress(checkpoint) == CheckpointProgress.COMPLETED:
        form.add_error(None, 'Tamamlanmış değerlendirme aşamasına yeni görev eklenemez.')
    elif form.is_valid():
        try:
            task = create_capstone_task(checkpoint=checkpoint, actor=request.user, values=form.cleaned_data)
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
    attempt_queryset = CapstoneSubmissionAttempt.objects.select_related('task__capstone_project__project')
    if not is_admin(request.user):
        attempt_queryset = attempt_queryset.filter(task__capstone_project__project__advisor=request.user)
    attempt = get_object_or_404(attempt_queryset, pk=attempt_id)
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


@login_required
@require_POST
def advisor_proposal_decide(request, proposal_id):
    raise Http404


@login_required
@require_POST
def advisor_checkpoint_evaluate(request, checkpoint_id):
    raise Http404


@login_required
@require_POST
def advisor_project_complete(request, project_id):
    capstone_project = get_object_or_404(CapstoneProject.objects.select_related('project'), pk=project_id)
    if not can_review_capstone(request.user, capstone_project):
        raise Http404
    try:
        complete_capstone_project(capstone_project=capstone_project, actor=request.user)
        messages.success(request, 'Bitirme projesi tamamlandı.')
    except ValidationError as error:
        messages.error(request, ' '.join(_validation_messages(error)))
    return redirect('capstone:advisor_project_detail', project_id=project_id)


def _can_download_submission_file(user, capstone_project):
    if not user.is_active or not can_view_capstone(user, capstone_project):
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
