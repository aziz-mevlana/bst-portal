from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from accounts.policies import is_admin, role_of
from .academic_forms import (AcademicReviewForm, AcademicSubmissionForm, ExtensionForm,
    HelpRequestForm, LiteratureForm, MeetingDecisionForm, MeetingRequestForm, PlanCheckpointForm, TextForm)
from .academic_models import (CapstoneAcademicSubmission, CapstoneAcademicSubmissionFile,
    CapstoneAdvisorPrivateNote, CapstoneChecklistItem, CapstoneHelpAttachment, CapstoneHelpMessage, CapstoneHelpRequest,
    CapstoneLiteratureVersion, CapstoneMeetingRequest, CapstonePlan, CapstonePlanCheckpoint,
    CapstonePlanTemplate, CapstoneStudentCheckpoint)
from .academic_services import (academic_overview, add_expectation, add_private_note,
    apply_plan_template, archive_checkpoint, change_advisor, claim_student, create_help_request,
    decide_meeting, enroll_student, extend_deadline, help_state, initialize_project,
    record_meeting, reply_help_request, request_meeting, resolve_help_request,
    review_checkpoint, review_literature, save_plan_checkpoint, save_plan_template,
    submit_checkpoint, tick_expectation, unassign_student, upload_literature)
from .models import CapstoneEnrollment, CapstoneProject, CapstoneTerm
from .policies import can_review_capstone, can_submit_capstone, can_view_capstone
from .services import complete_capstone_project


def _error(exc):
    if hasattr(exc, 'message_dict'):
        return ' '.join(message for items in exc.message_dict.values() for message in items)
    return ' '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)


def _project(user, project_id):
    project = get_object_or_404(CapstoneProject.objects.select_related('project__created_by', 'project__advisor', 'term'), pk=project_id)
    if not can_view_capstone(user, project):
        raise Http404
    return project


def _advisor(user):
    if not (is_admin(user) or (user.is_active and role_of(user) == 'teacher')):
        raise Http404


def _selected_plan(plans, user, selected_id):
    if not is_admin(user):
        return plans.filter(advisor=user).first()
    if selected_id:
        if not selected_id.isascii() or not selected_id.isdigit() or len(selected_id) > 19:
            return None
        advisor_id = int(selected_id)
        if advisor_id > 9223372036854775807:
            return None
        return plans.filter(advisor_id=advisor_id).first()
    return plans.first()


def workspace_context(project, user):
    overview = academic_overview(project)
    help_items = list(project.help_requests.select_related('checkpoint').prefetch_related(
        Prefetch('messages', queryset=CapstoneHelpMessage.objects.select_related('author').order_by('created_at', 'pk')),
        'attachments',
    ).order_by('-created_at'))
    for item in help_items:
        item.display_state = help_state(item)
    meetings = list(project.meetings.select_related('checkpoint', 'note').order_by('-created_at'))
    upcoming_meeting = min((item for item in meetings if item.status == item.Status.SCHEDULED
                            and item.scheduled_at and item.scheduled_at >= timezone.now()),
                           key=lambda item: item.scheduled_at, default=None)
    repository = getattr(project.project, 'repository', None)
    return {
        'capstone_project': project, 'overview': overview, 'help_items': help_items,
        'meetings': meetings, 'open_help_count': sum(not item.resolved_at for item in help_items),
        'upcoming_meeting': upcoming_meeting,
        'literature': project.literature_versions.select_related('review').order_by('-version'),
        'repository': repository,
        'is_advisor': can_review_capstone(user, project),
        'private_notes': project.private_advisor_notes.filter(advisor=user).order_by('-created_at')
                         if can_review_capstone(user, project) else (),
        'submission_form': AcademicSubmissionForm(), 'review_form': AcademicReviewForm(),
        'literature_form': LiteratureForm(project=project), 'help_form': HelpRequestForm(project=project),
        'meeting_form': MeetingRequestForm(project=project), 'meeting_decision_form': MeetingDecisionForm(),
        'extension_form': ExtensionForm(), 'text_form': TextForm(),
    }


@login_required
@require_GET
def advisor_center(request):
    _advisor(request.user)
    term = CapstoneTerm.objects.filter(is_active=True).first()
    enrollments = CapstoneEnrollment.objects.filter(term=term, is_active=True) if term else CapstoneEnrollment.objects.none()
    projects = CapstoneProject.objects.filter(term=term).exclude(project__development_status='cancelled').select_related(
        'project__created_by', 'project__advisor', 'term'
    ).prefetch_related('checkpoints__tasks__submission_attempts__review') if term else CapstoneProject.objects.none()
    if not is_admin(request.user):
        enrollments = enrollments.filter(advisor=request.user)
        projects = projects.filter(project__advisor=request.user)
    cards = []
    for project in projects:
        if project.checkpoints.exists():
            from .workflow import CheckpointProgress, capstone_overview, get_checkpoint_progress
            legacy = capstone_overview(project)
            total = project.checkpoints.count()
            approved = sum(get_checkpoint_progress(checkpoint) == CheckpointProgress.COMPLETED
                           for checkpoint in project.checkpoints.all())
            overview = {'current_stage': legacy['stage'], 'approved': approved, 'total': total,
                'percent': round(approved * 100 / total) if total else 0,
                'pending': legacy['pending_review_count'], 'revision': 0,
                'overdue': legacy['overdue_task_count'], 'next_due': legacy['next_deadline'],
                'completion_ready': legacy['completion_ready'], 'completed': legacy['completed']}
        else:
            overview = academic_overview(project)
        cards.append({'project': project, 'overview': overview})
    open_help = CapstoneHelpRequest.objects.filter(capstone_project__in=projects, resolved_at__isnull=True)
    requested_meetings = CapstoneMeetingRequest.objects.filter(
        capstone_project__in=projects, status=CapstoneMeetingRequest.Status.REQUESTED
    )
    return render(request, 'capstone/advisor_center.html', {
        'term': term, 'cards': cards, 'is_admin': is_admin(request.user),
        'student_count': enrollments.count(),
        'waiting_details': enrollments.exclude(student_id__in=projects.values('project__created_by_id')).count(),
        'active_count': sum(not item['overview'].get('completed') for item in cards),
        'completed_count': sum(bool(item['overview'].get('completed')) for item in cards),
        'pending_count': sum(item['overview']['pending'] for item in cards),
        'revision_count': sum(item['overview']['revision'] for item in cards),
        'overdue_count': sum(item['overview']['overdue'] for item in cards),
        'ready_count': sum(item['overview']['completion_ready'] for item in cards),
        'help_count': open_help.count(), 'meeting_count': requested_meetings.count(),
        'open_help': open_help.select_related('capstone_project__project__created_by').order_by('created_at')[:10],
        'requested_meetings': requested_meetings.select_related(
            'capstone_project__project__created_by').order_by('created_at')[:10],
    })


@login_required
@require_GET
def student_pool(request):
    _advisor(request.user)
    term = CapstoneTerm.objects.filter(is_active=True).first()
    pool = CapstoneEnrollment.objects.filter(term=term, is_active=True, advisor__isnull=True).select_related('student', 'student__profile') if term else ()
    mine = CapstoneEnrollment.objects.filter(term=term, is_active=True).select_related('student', 'advisor') if term else CapstoneEnrollment.objects.none()
    if not is_admin(request.user):
        mine = mine.filter(advisor=request.user)
    from django.contrib.auth import get_user_model
    eligible = get_user_model().objects.filter(is_active=True, profile__user_type__in=['student', 'staff_student'],
                                               profile__class_level='4').exclude(capstone_enrollments__term=term,
                                               capstone_enrollments__is_active=True).distinct().order_by('last_name', 'first_name', 'pk') if is_admin(request.user) and term else ()
    advisors = get_user_model().objects.filter(is_active=True, is_staff=False, is_superuser=False,
                                               profile__user_type='teacher').order_by('last_name', 'first_name', 'pk') if is_admin(request.user) else ()
    return render(request, 'capstone/student_pool.html', {'term': term, 'pool': pool, 'mine': mine,
                   'is_admin': is_admin(request.user), 'eligible': eligible, 'advisors': advisors})


@login_required
@require_POST
def student_enroll(request):
    if not is_admin(request.user):
        raise Http404
    term = get_object_or_404(CapstoneTerm, is_active=True)
    from django.contrib.auth import get_user_model
    student = get_object_or_404(get_user_model(), pk=request.POST.get('student_id'))
    try:
        enroll_student(term=term, student=student, actor=request.user)
        messages.success(request, 'Öğrenci resmi Bitirme Projesi listesine eklendi.')
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _error(exc))
    return redirect('capstone:student_pool')


@login_required
@require_POST
def advisor_claim(request, enrollment_id):
    _advisor(request.user)
    enrollment = get_object_or_404(CapstoneEnrollment, pk=enrollment_id)
    try:
        claim_student(enrollment=enrollment, advisor=request.user)
        messages.success(request, 'Öğrenciyi danışmanlığınıza aldınız.')
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _error(exc))
    return redirect('capstone:student_pool')


@login_required
@require_POST
def advisor_unassign(request, enrollment_id):
    enrollment = get_object_or_404(CapstoneEnrollment, pk=enrollment_id)
    if not (is_admin(request.user) or enrollment.advisor_id == request.user.pk):
        raise Http404
    if request.POST.get('confirm') != 'yes':
        messages.error(request, 'Danışmanlıktan çıkarma onayı gereklidir.')
    else:
        try:
            unassign_student(enrollment=enrollment, actor=request.user)
            messages.success(request, 'Danışmanlık kaldırıldı.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
    return redirect('capstone:student_pool')


@login_required
@require_POST
def advisor_change(request, enrollment_id):
    if not is_admin(request.user):
        raise Http404
    from django.contrib.auth import get_user_model
    enrollment = get_object_or_404(CapstoneEnrollment, pk=enrollment_id)
    advisor = get_object_or_404(get_user_model(), pk=request.POST.get('advisor_id'))
    try:
        change_advisor(enrollment=enrollment, new_advisor=advisor, actor=request.user,
                       reason=request.POST.get('reason', ''))
        messages.success(request, 'Danışman değiştirildi.')
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _error(exc))
    return redirect('capstone:student_pool')


@login_required
@require_GET
def plan_home(request):
    _advisor(request.user)
    term = CapstoneTerm.objects.filter(is_active=True).first()
    if not term:
        return render(request, 'capstone/plan.html', {'term': None})
    plans = CapstonePlan.objects.filter(term=term).select_related('advisor').order_by('advisor__last_name', 'advisor__first_name', 'pk')
    plan = _selected_plan(plans, request.user, request.GET.get('advisor'))
    if plan:
        plan = CapstonePlan.objects.filter(pk=plan.pk).prefetch_related('definitions__expectations').first()
    templates = CapstonePlanTemplate.objects.filter(advisor_id=plan.advisor_id) if plan else ()
    return render(request, 'capstone/plan.html', {'term': term, 'plan': plan,
                  'checkpoint_form': PlanCheckpointForm(), 'templates': templates,
                  'plans': plans if is_admin(request.user) else ()})


@login_required
@require_POST
def plan_checkpoint_save(request, plan_id, checkpoint_id=None):
    plan = get_object_or_404(CapstonePlan, pk=plan_id)
    if not (is_admin(request.user) or plan.advisor_id == request.user.pk and role_of(request.user) == 'teacher'):
        raise Http404
    checkpoint = get_object_or_404(CapstonePlanCheckpoint, pk=checkpoint_id, plan=plan) if checkpoint_id else None
    form = PlanCheckpointForm(request.POST, instance=checkpoint)
    if form.is_valid():
        try:
            save_plan_checkpoint(plan=plan, actor=request.user, checkpoint=checkpoint, **form.cleaned_data)
            messages.success(request, 'Kontrol planı güncellendi.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
    else:
        messages.error(request, _error(ValidationError(form.errors)))
    return redirect(f'{reverse("capstone:plan_home")}?advisor={plan.advisor_id}')


@login_required
@require_POST
def plan_checkpoint_archive(request, checkpoint_id):
    checkpoint = get_object_or_404(CapstonePlanCheckpoint, pk=checkpoint_id)
    if not (is_admin(request.user) or checkpoint.plan.advisor_id == request.user.pk and role_of(request.user) == 'teacher'):
        raise Http404
    if request.POST.get('confirm') == 'yes':
        try:
            archive_checkpoint(checkpoint=checkpoint, actor=request.user)
            messages.success(request, 'Kontrol noktası kaldırıldı veya geçmişi korunarak pasife alındı.')
        except ValidationError as exc:
            messages.error(request, _error(exc))
    return redirect(f'{reverse("capstone:plan_home")}?advisor={checkpoint.plan.advisor_id}')


@login_required
@require_POST
def expectation_add(request, checkpoint_id):
    checkpoint = get_object_or_404(CapstonePlanCheckpoint, pk=checkpoint_id)
    if not (is_admin(request.user) or checkpoint.plan.advisor_id == request.user.pk and role_of(request.user) == 'teacher'):
        raise Http404
    try:
        add_expectation(checkpoint=checkpoint, actor=request.user,
                        title=request.POST.get('title', '').strip(), order=int(request.POST.get('order', 1)))
        messages.success(request, 'Beklenenler maddesi eklendi.')
    except (ValidationError, ValueError) as exc:
        messages.error(request, _error(exc))
    return redirect(f'{reverse("capstone:plan_home")}?advisor={checkpoint.plan.advisor_id}')


@login_required
@require_POST
def template_save(request, plan_id):
    plan = get_object_or_404(CapstonePlan, pk=plan_id, advisor=request.user)
    title = request.POST.get('title', '').strip()
    if not title:
        messages.error(request, 'Şablon adı zorunludur.')
    else:
        save_plan_template(plan=plan, actor=request.user, title=title)
        messages.success(request, 'Kontrol planı şablon olarak kaydedildi.')
    return redirect(f'{reverse("capstone:plan_home")}?advisor={plan.advisor_id}')


@login_required
@require_POST
def template_apply(request, plan_id, template_id):
    plan = get_object_or_404(CapstonePlan, pk=plan_id, advisor=request.user)
    template = get_object_or_404(CapstonePlanTemplate, pk=template_id, advisor=request.user)
    due_dates = {item.pk: parse_datetime(request.POST.get(f'due_{item.pk}', '')) for item in template.definitions.all()}
    try:
        if any(value is None for value in due_dates.values()):
            raise ValidationError('Her kontrol noktası için tarih girin.')
        due_dates = {pk: timezone.make_aware(value) if timezone.is_naive(value) else value
                     for pk, value in due_dates.items()}
        apply_plan_template(plan=plan, template=template, actor=request.user, due_dates=due_dates)
        messages.success(request, 'Şablondan yeni dönem planı oluşturuldu.')
    except ValidationError as exc:
        messages.error(request, _error(exc))
    return redirect(f'{reverse("capstone:plan_home")}?advisor={plan.advisor_id}')


@login_required
@require_POST
def checklist_toggle(request, project_id, checkpoint_id, item_id):
    project = _project(request.user, project_id)
    checkpoint = get_object_or_404(CapstonePlanCheckpoint, pk=checkpoint_id)
    item = get_object_or_404(CapstoneChecklistItem, pk=item_id, checkpoint=checkpoint)
    if not can_submit_capstone(request.user, project):
        raise Http404
    tick_expectation(project=project, checkpoint=checkpoint, item=item, student=request.user,
                     checked=request.POST.get('checked') == 'yes')
    return redirect(reverse('capstone:student_home') + f'#checkpoint-{checkpoint_id}')


@login_required
@require_POST
def checkpoint_submit(request, project_id, checkpoint_id):
    project = _project(request.user, project_id)
    if not can_submit_capstone(request.user, project):
        raise Http404
    checkpoint = get_object_or_404(CapstonePlanCheckpoint, pk=checkpoint_id)
    form = AcademicSubmissionForm(request.POST)
    if form.is_valid():
        try:
            submit_checkpoint(project=project, checkpoint=checkpoint, student=request.user,
                note=form.cleaned_data['note'], files=request.FILES.getlist('files'),
                links=[line.strip() for line in form.cleaned_data['links'].splitlines() if line.strip()])
            messages.success(request, 'Tesliminiz kaydedildi.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
    else:
        messages.error(request, 'Teslim formunu kontrol edin.')
    return redirect(reverse('capstone:student_home') + f'#checkpoint-{checkpoint_id}')


@login_required
@require_POST
def checkpoint_review(request, submission_id):
    submission = get_object_or_404(CapstoneAcademicSubmission.objects.select_related('progress__capstone_project__project'), pk=submission_id)
    project = submission.progress.capstone_project
    if not can_review_capstone(request.user, project):
        raise Http404
    form = AcademicReviewForm(request.POST)
    if form.is_valid():
        try:
            review_checkpoint(submission=submission, actor=request.user, **form.cleaned_data)
            messages.success(request, 'Değerlendirme kaydedildi.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
    return redirect(reverse('capstone:advisor_project_detail', args=[project.pk]) + f'#checkpoint-{submission.progress.checkpoint_id}')


@login_required
@require_POST
def deadline_extend(request, project_id, checkpoint_id):
    project = _project(request.user, project_id)
    if not can_review_capstone(request.user, project):
        raise Http404
    checkpoint = get_object_or_404(CapstonePlanCheckpoint, pk=checkpoint_id)
    form = ExtensionForm(request.POST)
    if form.is_valid():
        try:
            extend_deadline(project=project, checkpoint=checkpoint, actor=request.user, **form.cleaned_data)
            messages.success(request, 'Öğrenciye özel ek süre verildi.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
    else:
        messages.error(request, 'Ek süre bilgilerini kontrol edin.')
    return redirect(reverse('capstone:advisor_project_detail', args=[project.pk]) + f'#checkpoint-{checkpoint_id}')


@login_required
@require_POST
def literature_upload(request, project_id):
    project = _project(request.user, project_id)
    if not can_submit_capstone(request.user, project):
        raise Http404
    form = LiteratureForm(request.POST, request.FILES, project=project)
    if form.is_valid():
        try:
            upload_literature(project=project, student=request.user, upload=form.cleaned_data['file'],
                              note=form.cleaned_data['note'], checkpoint=form.cleaned_data['checkpoint'])
            messages.success(request, 'Literatür raporu sürümü yüklendi.')
        except ValidationError as exc:
            messages.error(request, _error(exc))
    return redirect(reverse('capstone:student_home') + '#literature')


@login_required
@require_POST
def literature_review(request, version_id):
    version = get_object_or_404(CapstoneLiteratureVersion.objects.select_related('capstone_project__project'), pk=version_id)
    if not can_review_capstone(request.user, version.capstone_project):
        raise Http404
    form = AcademicReviewForm(request.POST)
    if form.is_valid():
        try:
            review_literature(version=version, actor=request.user, **form.cleaned_data)
            messages.success(request, 'Literatür raporu değerlendirildi.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
    return redirect(reverse('capstone:advisor_project_detail', args=[version.capstone_project_id]) + '#literature')


@login_required
@require_POST
def help_create(request, project_id):
    project = _project(request.user, project_id)
    if not can_submit_capstone(request.user, project):
        raise Http404
    form = HelpRequestForm(request.POST, request.FILES, project=project)
    if form.is_valid():
        try:
            create_help_request(project=project, student=request.user, subject=form.cleaned_data['subject'],
                description=form.cleaned_data['description'], upload=form.cleaned_data['file'],
                checkpoint=form.cleaned_data['checkpoint'])
            messages.success(request, 'Yardım talebi gönderildi.')
        except ValidationError as exc:
            messages.error(request, _error(exc))
    return redirect(reverse('capstone:student_home') + '#communication')


@login_required
@require_POST
def help_reply(request, help_id):
    item = get_object_or_404(CapstoneHelpRequest.objects.select_related('capstone_project__project'), pk=help_id)
    if not can_view_capstone(request.user, item.capstone_project):
        raise Http404
    try:
        reply_help_request(request_item=item, actor=request.user, content=request.POST.get('content', ''))
        messages.success(request, 'Yanıtınız kaydedildi.')
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, _error(exc))
    return redirect(reverse('capstone:student_home' if item.capstone_project.project.created_by_id == request.user.pk
                            else 'capstone:advisor_project_detail', args=[] if item.capstone_project.project.created_by_id == request.user.pk
                            else [item.capstone_project_id]) + '#communication')


@login_required
@require_POST
def help_resolve(request, help_id):
    item = get_object_or_404(CapstoneHelpRequest.objects.select_related('capstone_project__project'), pk=help_id)
    if not can_view_capstone(request.user, item.capstone_project):
        raise Http404
    resolve_help_request(request_item=item, actor=request.user)
    if item.capstone_project.project.created_by_id == request.user.pk:
        return redirect('capstone:student_home')
    return redirect('capstone:advisor_project_detail', project_id=item.capstone_project_id)


@login_required
@require_POST
def meeting_create(request, project_id):
    project = _project(request.user, project_id)
    if not can_submit_capstone(request.user, project):
        raise Http404
    form = MeetingRequestForm(request.POST, project=project)
    if form.is_valid():
        request_meeting(project=project, student=request.user, **form.cleaned_data)
        messages.success(request, 'Görüşme talebiniz gönderildi.')
    return redirect(reverse('capstone:student_home') + '#meetings')


@login_required
@require_POST
def meeting_decide(request, meeting_id):
    item = get_object_or_404(CapstoneMeetingRequest.objects.select_related('capstone_project__project'), pk=meeting_id)
    if not can_review_capstone(request.user, item.capstone_project):
        raise Http404
    form = MeetingDecisionForm(request.POST)
    if form.is_valid():
        try:
            decide_meeting(meeting=item, actor=request.user, decision=request.POST.get('decision'), **form.cleaned_data)
            messages.success(request, 'Görüşme talebi güncellendi.')
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
    return redirect(reverse('capstone:advisor_project_detail', args=[item.capstone_project_id]) + '#meetings')


@login_required
@require_POST
def meeting_record(request, meeting_id):
    item = get_object_or_404(CapstoneMeetingRequest.objects.select_related('capstone_project__project'), pk=meeting_id)
    if not can_review_capstone(request.user, item.capstone_project):
        raise Http404
    form = TextForm(request.POST)
    if form.is_valid():
        record_meeting(meeting=item, actor=request.user, content=form.cleaned_data['content'])
        messages.success(request, 'Görüşme notu kaydedildi.')
    return redirect(reverse('capstone:advisor_project_detail', args=[item.capstone_project_id]) + '#meetings')


@login_required
@require_POST
def private_note_add(request, project_id):
    project = _project(request.user, project_id)
    if not can_review_capstone(request.user, project):
        raise Http404
    form = TextForm(request.POST)
    if form.is_valid():
        add_private_note(project=project, actor=request.user, content=form.cleaned_data['content'])
        messages.success(request, 'Özel not kaydedildi.')
    return redirect(reverse('capstone:advisor_project_detail', args=[project_id]) + '#private-notes')


@require_GET
def academic_file(request, kind, file_id):
    if kind == 'submission':
        item = get_object_or_404(CapstoneAcademicSubmissionFile.objects.select_related(
            'submission__progress__capstone_project__project'), pk=file_id)
        project = item.submission.progress.capstone_project
    elif kind == 'literature':
        item = get_object_or_404(CapstoneLiteratureVersion.objects.select_related('capstone_project__project'), pk=file_id)
        project = item.capstone_project
    elif kind == 'help':
        item = get_object_or_404(CapstoneHelpAttachment.objects.select_related('request__capstone_project__project'), pk=file_id)
        project = item.request.capstone_project
    else:
        raise Http404
    if not can_view_capstone(request.user, project):
        raise Http404
    try:
        handle = item.file.open('rb')
    except (OSError, ValueError, FileNotFoundError):
        raise Http404 from None
    filename = item.original_name.replace('\r', '').replace('\n', '').replace('/', '').replace('\\', '')
    response = FileResponse(handle, as_attachment=True, filename=filename,
                            content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response


@login_required
@require_GET
def progress_matrix(request):
    _advisor(request.user)
    term = CapstoneTerm.objects.filter(is_active=True).first()
    plans = CapstonePlan.objects.filter(term=term).select_related('advisor').order_by('advisor__last_name', 'advisor__first_name', 'pk') if term else CapstonePlan.objects.none()
    plan = _selected_plan(plans, request.user, request.GET.get('advisor'))
    projects = list(CapstoneProject.objects.filter(term=term, project__advisor_id=plan.advisor_id).select_related(
        'project__created_by', 'project__advisor', 'term')) if plan else []
    definitions = list(plan.definitions.filter(is_active=True).prefetch_related('expectations')) if plan else []
    progress_by_project = {}
    if plan and projects:
        progress_records = CapstoneStudentCheckpoint.objects.filter(
            capstone_project__in=projects, checkpoint__plan=plan
        ).select_related('checkpoint').prefetch_related(
            'submissions__review', 'submissions__files', 'submissions__links', 'ticks'
        )
        for progress in progress_records:
            progress_by_project.setdefault(progress.capstone_project_id, {})[progress.checkpoint_id] = progress
    rows = [{'project': project, 'overview': academic_overview(project, preloaded=(
        plan, definitions, progress_by_project.get(project.pk, {})
    ))} for project in projects]
    return render(request, 'capstone/progress_matrix.html', {'term': term, 'plan': plan, 'rows': rows,
                   'definitions': definitions, 'plans': plans if is_admin(request.user) else ()})


@login_required
@require_GET
def process_report(request, project_id):
    project = _project(request.user, project_id)
    if not can_review_capstone(request.user, project):
        raise Http404
    from core.models import AuditLog
    enrollment_ids = CapstoneEnrollment.objects.filter(term=project.term,
        student_id=project.project.created_by_id).values_list('pk', flat=True)
    plan_ids = set(project.academic_progress.values_list('checkpoint__plan_id', flat=True))
    if project.project.advisor_id:
        plan_ids.update(project.project.advisor.capstone_plans.filter(term=project.term).values_list('pk', flat=True))
    scope = Q(metadata__project_id=project.pk) | Q(
        target_type='capstone.capstoneproject', target_id=str(project.pk))
    scope |= Q(target_type='capstone.capstoneenrollment', target_id__in=[str(pk) for pk in enrollment_ids])
    if plan_ids:
        scope |= Q(metadata__plan_id__in=list(plan_ids))
    scope |= Q(metadata__version_id__in=list(project.literature_versions.values_list('pk', flat=True)))
    scope |= Q(metadata__help_request_id__in=list(project.help_requests.values_list('pk', flat=True)))
    scope |= Q(metadata__meeting_id__in=list(project.meetings.values_list('pk', flat=True)))
    events = list(AuditLog.objects.filter(action__startswith='capstone.').filter(scope)
                  .select_related('actor').order_by('created_at'))
    labels = {
        'advisor_assigned': 'Danışman atandı', 'advisor_unassigned': 'Danışmanlık kaldırıldı',
        'advisor_changed': 'Danışman değiştirildi', 'advisor_note_created': 'Özel danışman notu eklendi',
        'enrollment_created': 'Bitirme Projesi listesine eklendi', 'project_initialized': 'Proje bilgileri tamamlandı',
        'project_created': 'Proje oluşturuldu', 'project_completed': 'Bitirme Projesi tamamlandı',
        'checkpoint_created': 'Kontrol noktası oluşturuldu', 'checkpoint_updated': 'Kontrol noktası güncellendi',
        'checkpoint_archived': 'Kontrol noktası pasife alındı', 'checkpoint_deleted': 'Kontrol noktası kaldırıldı',
        'checkpoint_submitted': 'Kontrol noktası teslim edildi', 'checkpoint_reviewed': 'Teslim değerlendirildi',
        'deadline_changed': 'Ortak son tarih değiştirildi', 'deadline_extended': 'Öğrenciye ek süre verildi',
        'expectation_created': 'Beklenen eklendi', 'literature_uploaded': 'Literatür raporu yüklendi',
        'literature_reviewed': 'Literatür raporu değerlendirildi', 'help_requested': 'Yardım talebi oluşturuldu',
        'help_replied': 'Yardım talebi yanıtlandı', 'help_resolved': 'Yardım talebi çözüldü',
        'meeting_requested': 'Görüşme talep edildi', 'meeting_scheduled': 'Görüşme planlandı',
        'meeting_cancelled': 'Görüşme iptal edildi', 'meeting_held': 'Görüşme gerçekleşti',
        'task_created': 'Görev oluşturuldu', 'submission_created': 'Görev teslimi yapıldı',
        'submission_reviewed': 'Görev teslimi değerlendirildi', 'checkpoint_evaluated': 'Eski değerlendirme kaydı',
        'proposal_submitted': 'Eski proje teklifi gönderildi', 'proposal_approved': 'Eski proje teklifi onaylandı',
        'proposal_rejected': 'Eski proje teklifi reddedildi', 'proposal_withdrawn': 'Eski proje teklifi geri çekildi',
        'plan_template_applied': 'Plan şablonu uygulandı', 'plan_template_saved': 'Plan şablonu kaydedildi',
    }
    for event in events:
        event.display_action = labels.get(event.action.removeprefix('capstone.'), 'Akademik süreç kaydı')
    return render(request, 'capstone/process_report.html', {'capstone_project': project, 'events': events,
                   'overview': academic_overview(project),
                   'historical_progress': project.academic_progress.select_related('checkpoint').all()})
