"""Teacher and student screens for active course project assignments."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch, Q
import uuid
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.policies import is_admin, is_teacher, role_of
from .course_work_forms import (CourseAssignmentCheckpointForm, CourseProjectAssignmentForm, CourseProjectWorkForm, CourseEvidenceForm, CourseReviewForm, CoursePlanFormSet)
from .course_work_models import (CourseAssignmentCheckpoint, CourseProjectAssignment,
    CourseProjectParticipation, CourseProjectTeam, CourseProjectWork)
from .course_work_services import (add_expectation, can_manage_assignment, can_view_work,
    create_team, create_work, join_assignment, join_team,
    override_team_member, rotate_invitation, save_checkpoint, assignment_has_history)
from .milestone_policies import can_review_project_milestone, can_submit_project_milestone
from .milestone_services import review_milestone, submit_milestone
from .models import Course, ProjectMilestone, ProjectMilestoneSubmission


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
    from .course_student_access import student_course_assignments
    participations = student_course_assignments(request.user)
    return render(request, 'projects/course_my_assignments.html', {
        'participations': participations,
        'active_participations': [p for p in participations if p.assignment.is_active],
        'past_participations': [p for p in participations if not p.assignment.is_active],
    })


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
    from .course_template_views import owned_template, plan_initial, cleaned_plan
    from .course_template_services import create_assignment_with_plan, BRIEF_FIELDS
    from .course_work_models import CourseProjectTemplate
    selected = request.POST.get('template_id') if request.method == 'POST' else request.GET.get('template')
    template = owned_template(request.user, selected) if selected else None
    if template and template.is_archived:
        raise Http404
    form = CourseProjectAssignmentForm(request.POST or None, instructor=request.user,
        initial={key: getattr(template,key) for key in BRIEF_FIELDS} if template else {})
    plan_formset = CoursePlanFormSet(request.POST or None, prefix='plan',
        initial=plan_initial(template.plan) if template else [])
    token = request.POST.get('creation_token', '') if request.method == 'POST' else str(uuid.uuid4())
    if request.method == 'POST':
        valid = form.is_valid(); plan_valid = plan_formset.is_valid()
        if valid and plan_valid:
            try:
                assignment = create_assignment_with_plan(instructor=request.user, plan=cleaned_plan(plan_formset),
                    creation_token=token, template=template, **form.cleaned_data)
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, 'Ders Projesi Çalışması oluşturuldu.')
                return redirect('projects:course_assignment_detail', assignment.pk)
    templates = CourseProjectTemplate.objects.filter(owner=request.user, is_archived=False).order_by('name')
    return render(request, 'projects/course_assignment_form.html', {'form': form, 'plan_formset': plan_formset,
        'templates': templates, 'selected_template': template, 'creation_token': token})


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
        'teams': assignment.teams.select_related('work').prefetch_related('participants__student'), 'rows': rows,
        'pending': pending, 'checkpoint_form': CourseAssignmentCheckpointForm(),
        'joined_count': len(participants),
        'team_count': assignment.teams.count(),
        'revision_count': sum(cell['state'] == 'REVISION_REQUIRED' for row in rows for cell in row['cells']),
        'overdue_count': sum(cell['state'] == 'OVERDUE' or cell['state'] == 'REVISION_REQUIRED' and cell['definition'].due_at < timezone.now() for row in rows for cell in row['cells']),
        'is_admin': is_admin(request.user),
        'can_delete_empty': not assignment_has_history(assignment),
    })


@login_required
@require_POST
def invitation_update(request, assignment_id):
    assignment = _assignment(request.user, assignment_id)
    action = request.POST.get('action')
    if action not in {'rotate', 'disable', 'enable'}:
        raise Http404
    try:
        rotate_invitation(assignment=assignment, actor=request.user, enabled=action != 'disable')
    except ValidationError as exc:
        messages.error(request, _message(exc))
        return redirect('projects:course_assignment_detail', assignment.pk)
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
        except CourseProjectAssignment.DoesNotExist:
            raise Http404
        return redirect('projects:course_invitation', token=token)
    team = participation.team if participation else None
    work = (CourseProjectWork.objects.filter(assignment=assignment, team=team).first() if team else
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
        messages.success(request, 'Ekip oluşturuldu.')
    except (ValidationError, PermissionDenied, CourseProjectParticipation.DoesNotExist) as exc:
        messages.error(request, _message(exc))
    return redirect('projects:course_invitation', token=assignment.invitation_token)


@login_required
@require_POST
def team_join(request, assignment_id, team_id):
    assignment = get_object_or_404(CourseProjectAssignment,
        pk=assignment_id, participants__student=request.user)
    try:
        team = join_team(assignment=assignment, student=request.user, team_id=team_id)
        messages.success(request, 'Ekibe katıldınız.')
        work = CourseProjectWork.objects.filter(assignment=assignment, team=team).first()
        if work:
            return redirect('projects:course_work_detail', work.pk)
    except (ValidationError, PermissionDenied, CourseProjectTeam.DoesNotExist, CourseProjectParticipation.DoesNotExist) as exc:
        messages.error(request, _message(exc))
    return redirect('projects:course_invitation', token=assignment.invitation_token)


@login_required
@require_POST
def team_override(request, assignment_id, student_id):
    assignment = _assignment(request.user, assignment_id)
    raw_team_id = request.POST.get('team_id', '')
    if raw_team_id and (not raw_team_id.isascii() or not raw_team_id.isdigit() or len(raw_team_id) > 19):
        raise Http404
    try:
        override_team_member(assignment=assignment, actor=request.user, student_id=student_id,
            team_id=int(raw_team_id) if raw_team_id else None,
            reason=request.POST.get('reason', ''))
        messages.success(request, 'Ekip üyeliği güncellendi.')
    except (ValidationError, CourseProjectParticipation.DoesNotExist, CourseProjectTeam.DoesNotExist) as exc:
        messages.error(request, _message(exc))
    return redirect(f'{reverse("projects:course_assignment_detail", args=[assignment.pk])}?section=participants')


@login_required
@require_POST
def work_create(request, assignment_id):
    assignment = get_object_or_404(CourseProjectAssignment,
        pk=assignment_id, participants__student=request.user)
    participation = get_object_or_404(CourseProjectParticipation, assignment=assignment, student=request.user)
    existing = CourseProjectWork.objects.filter(assignment=assignment,
        **({'team_id': participation.team_id} if participation.team_id else {'owner': request.user})).first()
    if existing and can_view_work(request.user, existing):
        return redirect('projects:course_work_detail', existing.pk)
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
    progress = work.project.milestones.all()
    if work.assignment.is_active:
        progress = progress.filter(assignment_checkpoint__is_active=True)
    milestones = list(progress
                      .select_related('assignment_checkpoint').prefetch_related(
                          'assignment_checkpoint__expected_items',
                          'submissions__review', 'submissions__files', 'submissions__links', 'submissions__references'))
    active_milestones = [item for item in milestones if item.assignment_checkpoint.is_active]
    approved = sum(item.state == 'APPROVED' for item in active_milestones)
    can_submit = can_submit_project_milestone(request.user, milestones[0]) if milestones else False
    can_review = can_review_project_milestone(request.user, milestones[0]) if milestones else False
    manager = can_manage_assignment(request.user, work.assignment)
    private_by_review = {}
    private_total = {'earned': 0, 'maximum': 0}
    if manager:
        from .course_work_models import CoursePrivateEvaluation
        for evaluation in CoursePrivateEvaluation.objects.filter(review__submission__milestone__project=work.project).select_related('actor').order_by('pk'):
            private_by_review.setdefault(evaluation.review_id, []).append(evaluation)
    for milestone in milestones:
        milestone.can_submit = can_submit
        milestone.can_review = can_review
        milestone.submission_form = CourseEvidenceForm(checkpoint=milestone.assignment_checkpoint)
        file_rule = milestone.assignment_checkpoint.evidence_requirements['FILE']
        milestone.files_enabled = file_rule['mode'] != 'DISABLED'
        milestone.files_required = file_rule['mode'] == 'REQUIRED'
        milestone.file_mode_label = 'Zorunlu' if milestone.files_required else 'Opsiyonel'
        if manager:
            milestone.review_form = CourseReviewForm(checkpoint=milestone.assignment_checkpoint)
            for submission in milestone.submissions.all():
                if hasattr(submission, 'review'):
                    submission.private_history = private_by_review.get(submission.review.pk, [])
                    submission.private_latest = submission.private_history[-1] if submission.private_history else None
                    submission.private_form = CourseReviewForm(checkpoint=milestone.assignment_checkpoint, private_only=True,
                        initial={'private_note': submission.private_latest.note if submission.private_latest else '',
                                 'private_score': submission.private_latest.score if submission.private_latest else None})
            latest = milestone.latest_submission
            evaluation = getattr(latest, 'private_latest', None) if latest else None
            if milestone.assignment_checkpoint.is_active and evaluation and evaluation.score is not None:
                private_total['earned'] += evaluation.score
                private_total['maximum'] += evaluation.max_points
        # Public review projection contains feedback and decision only. Private annotations
        # never enter student contexts, even through submission.review relations.

    template = ('projects/course_work_detail_teacher.html' if can_manage_assignment(request.user, work.assignment)
                else 'projects/course_work_detail.html')
    from core.models import AuditLog
    submission_ids = [str(item.pk) for milestone in milestones for item in milestone.submissions.all()]
    scope = Q(target_type='projects.courseprojectassignment', target_id=str(work.assignment_id))
    scope |= Q(target_type='projects.courseprojectwork', target_id=str(work.pk))
    scope |= Q(target_type='projects.project', target_id=str(work.project_id))
    scope |= Q(target_type='projects.projectmilestone', target_id__in=[str(item.pk) for item in milestones])
    scope |= Q(target_type='projects.projectmilestonesubmission', target_id__in=submission_ids)
    scope |= Q(metadata__project_id=work.project_id, action__startswith='project.')
    review_ids = [str(item.review.pk) for milestone in milestones for item in milestone.submissions.all() if hasattr(item, 'review')]
    scope |= Q(target_type='projects.projectmilestonereview', target_id__in=review_ids)
    history = list(AuditLog.objects.filter(scope).select_related('actor').order_by('-created_at'))
    labels = {
        'course.assignment_created': 'Çalışma oluşturuldu',
        'course.assignment_updated': 'Çalışma düzenlendi',
        'course.assignment_cancelled': 'Çalışma iptal edildi',
        'course.assignment_reactivated': 'Çalışma yeniden aktifleştirildi',
        'course.work_created': 'Proje bilgileri tamamlandı',
        'project.milestone.submitted': 'Kontrol noktası teslim edildi',
        'project.milestone.reviewed': 'Teslim değerlendirildi',
    }
    for event in history:
        event.display_action = labels.get(event.action, 'Akademik işlem kaydedildi')
    return render(request, template, {
        'history': history,
        'members': work.team.participants.select_related('student') if work.team_id else (),
        'work': work, 'milestones': milestones, 'approved': approved,
        'total': len(active_milestones),
        **({'private_total': private_total, 'manager': True} if manager else {}),
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
    form = CourseEvidenceForm(request.POST, checkpoint=milestone.assignment_checkpoint)
    if form.is_valid():
        try:
            submit_milestone(milestone=milestone, actor=request.user,
                note=request.POST.get('completion_note', ''),
                links=[line.strip() for line in request.POST.get('evidence_links', '').splitlines() if line.strip()],
                files=request.FILES.getlist('files'),
                references=CourseEvidenceForm.parse_references(request.POST.get('references', '')))
            messages.success(request, 'Kontrol noktası teslim edildi.')
        except ValidationError as exc:
            messages.error(request, _message(exc))
    else:
        messages.error(request, str(form.errors))
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
    form = CourseReviewForm(request.POST, checkpoint=submission.milestone.assignment_checkpoint)
    if form.is_valid():
        try:
            review_milestone(submission=submission, actor=request.user, **{**form.cleaned_data, 'private_score': form.cleaned_data.get('private_score') if 'private_score' in form.fields else _forged_score(request.POST)})
            messages.success(request, 'Değerlendirme kaydedildi.')
        except ValidationError as exc:
            messages.error(request, _message(exc))
    else:
        messages.error(request, str(form.errors))
    return redirect(f'{reverse("projects:course_work_detail", args=[work.pk])}#checkpoint-{submission.milestone_id}')


@login_required
@require_http_methods(['GET', 'POST'])
def assignment_edit(request, assignment_id):
    from .course_work_services import edit_assignment
    assignment = _assignment(request.user, assignment_id)
    if not assignment.is_active:
        raise Http404
    form = CourseProjectAssignmentForm(request.POST or None, instance=assignment, instructor=assignment.instructor)
    if request.method == 'POST' and form.is_valid():
        try:
            edit_assignment(assignment=assignment, actor=request.user,
                            values={key: value for key, value in form.cleaned_data.items() if key != 'course'})
        except ValidationError as exc:
            form.add_error(None, exc)
        except CourseProjectAssignment.DoesNotExist:
            raise Http404
        else:
            messages.success(request, 'Ders Projesi Çalışması güncellendi.')
            return redirect('projects:course_assignment_detail', assignment.pk)
    return render(request, 'projects/course_assignment_form.html', {'form': form, 'assignment': assignment})


@login_required
@require_http_methods(['GET', 'POST'])
def assignment_action(request, assignment_id, action):
    from .course_work_services import (cancel_assignment, reactivate_assignment,
                                      delete_empty_assignment, purge_assignment)
    if action not in {'cancel', 'delete', 'purge', 'reactivate'}:
        raise Http404
    if action in {'purge', 'reactivate'} and not is_admin(request.user):
        raise Http404
    assignment = _assignment(request.user, assignment_id)
    labels = {'cancel': 'İptal Et', 'delete': 'Sil', 'purge': 'Kalıcı Sil', 'reactivate': 'Yeniden Aktifleştir'}
    if request.method == 'POST':
        if request.POST.get('confirm') != 'yes' or (action == 'purge' and request.POST.get('confirmation') != 'KALICI OLARAK SİL'):
            messages.error(request, 'İşlem onayı gereklidir.')
        else:
            try:
                reason = request.POST.get('reason', '')
                if action in {'cancel', 'reactivate'}:
                    raw_version = request.POST.get('version', '')
                    if not raw_version.isascii() or not raw_version.isdigit() or len(raw_version) > 10:
                        raise ValidationError('İşlem sürümü geçersiz. Sayfayı yenileyin.')
                    operation = cancel_assignment if action == 'cancel' else reactivate_assignment
                    _, changed = operation(assignment=assignment, actor=request.user,
                        reason=reason, expected_version=int(raw_version))
                    messages.success(request, 'İşlem tamamlandı.' if changed else 'Çalışma zaten bu durumda; işlem tekrarlanmadı.')
                    return redirect('projects:course_assignment_detail', assignment.pk)
                operation = purge_assignment if action == 'purge' else delete_empty_assignment
                operation(assignment=assignment, actor=request.user, reason=reason)
                messages.success(request, 'Ders Projesi Çalışması silindi.')
                return redirect('projects:course_assignment_list')
            except ProtectedError:
                messages.error(request, 'Başka kayıtlara bağlı veri bulundu; güvenli silme yapılamadı. Çalışma korundu.')
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _message(exc))
            except CourseProjectAssignment.DoesNotExist:
                raise Http404
        try:
            assignment.refresh_from_db()
        except CourseProjectAssignment.DoesNotExist:
            raise Http404
    return render(request, 'projects/course_assignment_action.html',
        {'assignment': assignment, 'action': action, 'action_label': labels[action]})


def _forged_score(data):
    if data.get('private_score'):
        raise ValidationError('Puanlama bu kontrol noktasında kapalı.')
    return None


@login_required
@require_POST
def private_evaluation_update(request, work_id, review_id):
    from .models import ProjectMilestoneReview
    from .milestone_services import update_private_evaluation
    work = _work(request.user, work_id)
    if not can_manage_assignment(request.user, work.assignment):
        raise Http404
    review = get_object_or_404(ProjectMilestoneReview.objects.select_related('submission__milestone__assignment_checkpoint'),
        pk=review_id, submission__milestone__project=work.project,
        submission__milestone__assignment_checkpoint__assignment=work.assignment)
    form = CourseReviewForm(request.POST, checkpoint=review.submission.milestone.assignment_checkpoint, private_only=True)
    if form.is_valid():
        try:
            score = form.cleaned_data.get('private_score') if 'private_score' in form.fields else _forged_score(request.POST)
            update_private_evaluation(review=review, actor=request.user, note=form.cleaned_data['private_note'], score=score,
                expected_id=int(request.POST.get('expected_id', '')))
        except (ValueError, ValidationError) as exc:
            messages.error(request, _message(exc))
    else:
        messages.error(request, str(form.errors))
    return redirect('projects:course_work_detail', work.pk)
