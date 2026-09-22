import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ProjectMilestoneForm, ProjectMilestoneReviewForm, ProjectMilestoneSubmissionForm
from .milestone_policies import can_manage_project_milestones, can_submit_project_milestone, can_view_project_milestone_evidence
from .milestone_services import review_milestone, save_milestone, submit_milestone
from .models import Project, ProjectMilestone, ProjectMilestoneSubmission, ProjectMilestoneSubmissionFile


@login_required
def milestone_edit(request, project_id, milestone_id=None):
    project = get_object_or_404(Project.objects.select_related('project_type'), pk=project_id)
    if not can_manage_project_milestones(request.user, project):
        raise Http404
    milestone = get_object_or_404(ProjectMilestone, pk=milestone_id, project=project) if milestone_id else None
    if milestone:
        milestone._acting_user = request.user
    form = ProjectMilestoneForm(request.POST or None, instance=milestone)
    if request.method == 'POST' and form.is_valid():
        try:
            saved = save_milestone(project=project, actor=request.user, values=form.cleaned_data, milestone=milestone)
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
        else:
            return redirect(f'{project.get_absolute_url()}#milestone-{saved.pk}')
    return render(request, 'projects/milestone_form.html', {'project': project, 'form': form, 'milestone': milestone})


@login_required
@require_POST
def milestone_submit(request, milestone_id):
    milestone = get_object_or_404(ProjectMilestone.objects.select_related('project', 'project__project_type'), pk=milestone_id)
    if not can_submit_project_milestone(request.user, milestone):
        raise Http404
    form = ProjectMilestoneSubmissionForm(request.POST)
    if form.is_valid():
        try:
            submit_milestone(milestone=milestone, actor=request.user,
                             note=form.cleaned_data['completion_note'],
                             links=[line.strip() for line in form.cleaned_data['evidence_links'].splitlines() if line.strip()],
                             files=request.FILES.getlist('files'))
            messages.success(request, 'Aşama teslim edildi.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
    else:
        messages.error(request, 'Teslim formunu kontrol edin.')
    return redirect(f'{milestone.project.get_absolute_url()}#milestone-{milestone.pk}')


@login_required
@require_POST
def milestone_review(request, submission_id):
    submission = get_object_or_404(ProjectMilestoneSubmission.objects.select_related('milestone', 'milestone__project', 'milestone__project__project_type'), pk=submission_id)
    milestone = submission.milestone
    if not can_manage_project_milestones(request.user, milestone.project):
        raise Http404
    form = ProjectMilestoneReviewForm(request.POST)
    if form.is_valid():
        try:
            review_milestone(submission=submission, actor=request.user, **form.cleaned_data)
            messages.success(request, 'Değerlendirme kaydedildi.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
    else:
        messages.error(request, 'Değerlendirme formunu kontrol edin.')
    return redirect(f'{milestone.project.get_absolute_url()}#milestone-{milestone.pk}')


@login_required
def milestone_file(request, file_id):
    item = get_object_or_404(ProjectMilestoneSubmissionFile.objects.select_related(
        'submission', 'submission__milestone', 'submission__milestone__project',
        'submission__milestone__project__project_type'), pk=file_id)
    if not can_view_project_milestone_evidence(request.user, item.submission):
        raise Http404
    try:
        handle = item.file.open('rb')
    except (OSError, ValueError, FileNotFoundError):
        raise Http404 from None
    content_type = mimetypes.guess_type(item.original_name)[0] or 'application/octet-stream'
    response = FileResponse(handle, as_attachment=True, filename=item.original_name, content_type=content_type)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
