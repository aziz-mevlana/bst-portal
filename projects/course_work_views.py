"""Teacher and student screens for active course project assignments."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.policies import is_admin, is_teacher, role_of
from .course_work_forms import CourseAssignmentCheckpointForm, CourseProjectAssignmentForm, CourseProjectWorkForm
from .course_work_models import (CourseAssignmentCheckpoint, CourseProjectAssignment,
    CourseProjectParticipation, CourseProjectTeam, CourseProjectWork)
from .course_work_services import (add_expectation, can_manage_assignment, can_view_work,
    create_assignment, create_team, create_work, join_assignment, join_team,
    override_team_member, rotate_invitation, save_checkpoint)
from .forms import ProjectMilestoneReviewForm, ProjectMilestoneSubmissionForm
from .milestone_policies import can_review_project_milestone, can_submit_project_milestone
from .milestone_services import review_milestone, submit_milestone
from .models import Course, CourseInstructor, ProjectMilestone, ProjectMilestoneSubmission


def _message(exc):
    return ' '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)


def _assignment(user, assignment_id):
    assignment = get_object_or_404(CourseProjectAssignment.objects.select_related('course', 'instructor'), pk=assignment_id)
    if not can_manage_assignment(user, assignment):
        raise Http404
    return assignment


def _work(user, work_id):
    work = get_object_or_404(CourseProjectWork.objects.select_related(
        'assignment__course', 'assignment__instructor', 'project', 'team', 'owner'), pk=work_id)
    if not can_view_work(user, work):
        raise Http404
    return work


@login_required
@require_GET
def my_assignments(request):
    if role_of(request.user) not in {'student', 'staff_student'}:
        raise Http404
    participations = list(CourseProjectParticipation.objects.filter(student=request.user)
                          .select_related('assignment__course', 'team').order_by('-joined_at'))
    individual = dict(CourseProjectWork.objects.filter(owner=request.user)
                      .values_list('assignment_id', 'pk'))
    team_works = dict(CourseProjectWork.objects.filter(team_id__in=[item.team_id for item in participations if item.team_id])
                      .values_list('team_id', 'pk'))
    for item in participations:
        item.work_id = team_works.get(item.team_id) if item.team_id else individual.get(item.assignment_id)
    return render(request, 'projects/course_my_assignments.html', {'participations': participations})


@login_required
@require_GET
def assignment_list(request):
    if not (is_teacher(request.user) or is_admin(request.user)):
        raise Http404
    assignments = CourseProjectAssignment.objects.select_related('course', 'instructor').order_by('-created_at')
    courses = Course.objects.filter(is_active=True, instructor_assignments__instructor=request.user,
        instructor_assignments__is_active=True).exclude(code__in=['BST 401', 'BST 402']).distinct()
    if not is_admin(request.user):
        assignments = assignments.filter(instructor=request.user,
            course__instructor_assignments__instructor=request.user,
            course__instructor_assignments__is_active=True).distinct()
    course_slug = request.GET.get('course', '')
    if course_slug:
        assignments = assignments.filter(course__slug=course_slug)
    return render(request, 'projects/course_assignment_list.html',
                  {'assignments': assignments, 'courses': courses, 'course_slug': course_slug})


@login_required
@require_http_methods(['GET', 'POST'])
def assignment_create(request):
    if not is_teacher(request.user) or not request.user.is_active:
        raise Http404
    form = CourseProjectAssignmentForm(request.POST or None, instructor=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            assignment = create_assignment(instructor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Ders Projesi Çalışması oluşturuldu.')
            return redirect('projects:course_assignment_detail', assignment.pk)
    return render(request, 'projects/course_assignment_form.html', {'form': form})


@login_required
@require_GET
def assignment_detail(request, assignment_id):
    assignment = _assignment(request.user, assignment_id)
    section = request.GET.get('section', 'overview')
    if section not in {'overview', 'participants', 'teams', 'plan', 'matrix', 'pending'}:
        section = 'overview'
    definitions = list(assignment.checkpoints.prefetch_related('expected_items').order_by('order'))
    works = list(assignment.works.select_related('project', 'owner', 'team').prefetch_related(
        Prefetch('project__milestones', queryset=ProjectMilestone.objects.select_related(
            'assignment_checkpoint').prefetch_related('submissions__review'))))
    participants = list(assignment.participants.select_related('student', 'team').order_by('joined_at'))
    rows = []
    pending = []
    active_definitions = [item for item in definitions if item.is_active]
    for work in works:
        by_definition = {item.assignment_checkpoint_id: item for item in work.project.milestones.all()}
        cells = []
        for definition in active_definitions:
            milestone = by_definition.get(definition.pk)
            state = milestone.state if milestone else 'NOT_SUBMITTED'
            if state == 'NOT_SUBMITTED' and definition.due_at < timezone.now():
                state = 'OVERDUE'
            cells.append({'definition': definition, 'state': state, 'milestone': milestone})
            if milestone and state == 'AWAITING_REVIEW':
                pending.append({'work': work, 'milestone': milestone, 'submission': milestone.latest_submission})
        work.completed_count = sum(cell['state'] == 'APPROVED' for cell in cells)
        work.total_count = len(active_definitions)
        rows.append({'work': work, 'cells': cells})
    return render(request, 'projects/course_assignment_detail.html', {
        'assignment': assignment, 'section': section, 'definitions': definitions,
        'active_definitions': active_definitions, 'participants': participants,
        'teams': assignment.teams.prefetch_related('participants__student'), 'rows': rows,
        'pending': pending, 'checkpoint_form': CourseAssignmentCheckpointForm(),
        'joined_count': len(participants),
    })


@login_required
@require_POST
def invitation_update(request, assignment_id):
    assignment = _assignment(request.user, assignment_id)
    action = request.POST.get('action')
    if action not in {'rotate', 'disable', 'enable'}:
        raise Http404
    rotate_invitation(assignment=assignment, actor=request.user, enabled=action != 'disable')
    messages.success(request, 'Katılım bağlantısı güncellendi. Eski bağlantı geçersizdir.')
    return redirect('projects:course_assignment_detail', assignment.pk)


@login_required
@require_http_methods(['GET', 'POST'])
def invitation(request, token):
    assignment = get_object_or_404(CourseProjectAssignment.objects.select_related('course', 'instructor'),
                                   invitation_token=token)
    if not request.user.is_active or role_of(request.user) not in {'student', 'staff_student'}:
        raise Http404
    participation = CourseProjectParticipation.objects.filter(assignment=assignment, student=request.user).select_related('team').first()
    if request.method == 'POST':
        try:
            participation = join_assignment(token=token, student=request.user)
            messages.success(request, 'Ders Projesi Çalışmasına katıldınız.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _message(exc))
        return redirect('projects:course_invitation', token=token)
    team = participation.team if participation else None
    work = (CourseProjectWork.objects.filter(team=team).first() if team else
            CourseProjectWork.objects.filter(assignment=assignment, owner=request.user).first()) if participation else None
    teams = assignment.teams.prefetch_related('participants') if assignment.mode == assignment.Mode.GROUP else ()
    return render(request, 'projects/course_invitation.html', {
        'assignment': assignment, 'participation': participation, 'team': team,
        'teams': teams, 'work': work, 'work_form': CourseProjectWorkForm(),
        'can_join': assignment.is_active and assignment.invitation_enabled and timezone.now() <= assignment.join_deadline,
    })


@login_required
@require_POST
def team_create(request, assignment_id):
    assignment = get_object_or_404(CourseProjectAssignment,
        pk=assignment_id, participants__student=request.user)
    try:
        create_team(assignment=assignment, student=request.user, name=request.POST.get('name', ''))
        messages.success(request, 'Takım oluşturuldu.')
    except (ValidationError, PermissionDenied, CourseProjectParticipation.DoesNotExist) as exc:
        messages.error(request, _message(exc))
    return redirect('projects:course_invitation', token=assignment.invitation_token)


@login_required
@require_POST
def team_join(request, assignment_id, team_id):
    assignment = get_object_or_404(CourseProjectAssignment,
        pk=assignment_id, participants__student=request.user)
    try:
        join_team(assignment=assignment, student=request.user, team_id=team_id)
        messages.success(request, 'Takıma katıldınız.')
    except (ValidationError, PermissionDenied, CourseProjectTeam.DoesNotExist, CourseProjectParticipation.DoesNotExist) as exc:
        messages.error(request, _message(exc))
    return redirect('projects:course_invitation', token=assignment.invitation_token)


@login_required
@require_POST
def team_override(request, assignment_id, student_id):
    assignment = _assignment(request.user, assignment_id)
    raw_team_id = request.POST.get('team_id', '')
    if raw_team_id and not raw_team_id.isdigit():
        raise Http404
    try:
        override_team_member(assignment=assignment, actor=request.user, student_id=student_id,
            team_id=int(raw_team_id) if raw_team_id else None,
            reason=request.POST.get('reason', ''))
        messages.success(request, 'Takım üyeliği güncellendi.')
    except (ValidationError, CourseProjectParticipation.DoesNotExist, CourseProjectTeam.DoesNotExist) as exc:
        messages.error(request, _message(exc))
    return redirect(f'{reverse("projects:course_assignment_detail", args=[assignment.pk])}?section=participants')


@login_required
@require_POST
def work_create(request, assignment_id):
    assignment = get_object_or_404(CourseProjectAssignment,
        pk=assignment_id, participants__student=request.user)
    form = CourseProjectWorkForm(request.POST)
    if form.is_valid():
        try:
            work = create_work(assignment=assignment, student=request.user, **form.cleaned_data)
        except (ValidationError, PermissionDenied, CourseProjectParticipation.DoesNotExist) as exc:
            messages.error(request, _message(exc))
        else:
            messages.success(request, 'Proje bilgileriniz kaydedildi.')
            return redirect('projects:course_work_detail', work.pk)
    else:
        messages.error(request, 'Proje bilgilerini kontrol edin.')
    return redirect('projects:course_invitation', token=assignment.invitation_token)


@login_required
@require_GET
def work_detail(request, work_id):
    work = _work(request.user, work_id)
    milestones = list(work.project.milestones.filter(assignment_checkpoint__is_active=True)
                      .select_related('assignment_checkpoint').prefetch_related(
                          'submissions__review', 'submissions__files', 'submissions__links'))
    approved = sum(item.state == 'APPROVED' for item in milestones)
    can_submit = can_submit_project_milestone(request.user, milestones[0]) if milestones else False
    can_review = can_review_project_milestone(request.user, milestones[0]) if milestones else False
    for milestone in milestones:
        milestone.can_submit = can_submit
        milestone.can_review = can_review
    template = ('projects/course_work_detail_teacher.html' if can_manage_assignment(request.user, work.assignment)
                else 'projects/course_work_detail.html')
    return render(request, template, {
        'work': work, 'milestones': milestones, 'approved': approved,
        'total': len(milestones), 'submission_form': ProjectMilestoneSubmissionForm(),
        'review_form': ProjectMilestoneReviewForm(),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def checkpoint_save(request, assignment_id, checkpoint_id=None):
    assignment = _assignment(request.user, assignment_id)
    checkpoint = get_object_or_404(CourseAssignmentCheckpoint, pk=checkpoint_id, assignment=assignment) if checkpoint_id else None
    form = CourseAssignmentCheckpointForm(request.POST or None, instance=checkpoint)
    if request.method == 'POST' and form.is_valid():
        try:
            save_checkpoint(assignment=assignment, actor=request.user,
                            values=form.cleaned_data, checkpoint=checkpoint)
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
        else:
            return redirect(f'{reverse("projects:course_assignment_detail", args=[assignment.pk])}?section=plan')
    return render(request, 'projects/course_checkpoint_form.html',
                  {'assignment': assignment, 'checkpoint': checkpoint, 'form': form})


@login_required
@require_POST
def expectation_add(request, checkpoint_id):
    checkpoint = get_object_or_404(CourseAssignmentCheckpoint.objects.select_related('assignment'), pk=checkpoint_id)
    if not can_manage_assignment(request.user, checkpoint.assignment):
        raise Http404
    try:
        add_expectation(checkpoint=checkpoint, actor=request.user, title=request.POST.get('title', ''))
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _message(exc))
    return redirect(f'{reverse("projects:course_assignment_detail", args=[checkpoint.assignment_id])}?section=plan')


@login_required
@require_POST
def work_submit(request, work_id, milestone_id):
    work = _work(request.user, work_id)
    milestone = get_object_or_404(ProjectMilestone, pk=milestone_id, project=work.project,
                                  assignment_checkpoint__assignment=work.assignment)
    if not can_submit_project_milestone(request.user, milestone):
        raise Http404
    form = ProjectMilestoneSubmissionForm(request.POST)
    if form.is_valid():
        try:
            submit_milestone(milestone=milestone, actor=request.user,
                note=form.cleaned_data['completion_note'],
                links=[line.strip() for line in form.cleaned_data['evidence_links'].splitlines() if line.strip()],
                files=request.FILES.getlist('files'))
            messages.success(request, 'Kontrol noktası teslim edildi.')
        except ValidationError as exc:
            messages.error(request, _message(exc))
    return redirect(f'{reverse("projects:course_work_detail", args=[work.pk])}#checkpoint-{milestone.pk}')


@login_required
@require_POST
def work_review(request, work_id, submission_id):
    work = _work(request.user, work_id)
    submission = get_object_or_404(ProjectMilestoneSubmission.objects.select_related('milestone'),
        pk=submission_id, milestone__project=work.project,
        milestone__assignment_checkpoint__assignment=work.assignment)
    if not can_review_project_milestone(request.user, submission.milestone):
        raise Http404
    form = ProjectMilestoneReviewForm(request.POST)
    if form.is_valid():
        try:
            review_milestone(submission=submission, actor=request.user, **form.cleaned_data)
            messages.success(request, 'Değerlendirme kaydedildi.')
        except ValidationError as exc:
            messages.error(request, _message(exc))
    return redirect(f'{reverse("projects:course_work_detail", args=[work.pk])}#checkpoint-{submission.milestone_id}')
