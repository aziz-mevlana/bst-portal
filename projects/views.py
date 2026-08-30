import hashlib
import hmac
import logging
import mimetypes
from urllib.parse import urlsplit

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_safe
from .models import (
    Project, ProjectRequest, ProjectCategory, Technology, ProjectUpdate,
    ProjectAchievement, ProjectCaseStudy, ProjectComment, ProjectContribution,
    ProjectFeedback, ProjectMedia, ProjectProgram, ProjectRequestApplication,
    ProjectFeature, ProjectLike, ProjectRepository, ProjectSave, ProjectType, ProjectView,
    ProjectWritingSuggestion, Team, TeamInvitation, TeamMembership, TeamOpenRole,
)
from .forms import (
    ApplicationReviewForm, ProjectAchievementForm, ProjectCaseStudyForm,
    ProjectContributionForm, ProjectForm, ProjectMediaForm, ProjectUpdateForm,
    ProjectCommentForm, ProjectFeedbackForm, ProjectImageUploadForm, ProjectRepositoryForm,
    ProjectRequestApplicationForm, RequestForm, TeamForm, TeamInviteForm, TeamOpenRoleForm,
)
from .services import accept_project_request_application
from .team_services import (
    cancel_invitation, can_disband_team, create_team, disband_team, invite_user,
    respond_to_invitation,
)
from core.audit import record_audit_event
from core.analytics import record_analytics_event
from core.notifications import create_notification
from core.rate_limit import is_rate_limited
from accounts.permissions import ensure_full_participation_account, ensure_interactive_account
from accounts.validators import validate_public_website
from django.template.loader import render_to_string

PAGE_SIZE = 12
logger = logging.getLogger(__name__)


def _safe_offset(request):
    try:
        return max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        return 0


def _user_type(user):
    profile = getattr(user, 'profile', None) if user.is_authenticated else None
    return getattr(profile, 'user_type', None)


def _is_platform_staff(user):
    """True only for real Django administrators, never for student roles."""

    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def _is_django_admin(user):
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def _can_view_project(user, project):
    if project.visibility in {'public', 'unlisted'} and project.approval_status == 'approved':
        return True
    if not user.is_authenticated:
        return False
    return bool(
        user == project.created_by
        or user == project.advisor
        or project.team.filter(pk=user.pk).exists()
        or _is_platform_staff(user)
    )


def _can_manage_project(user, project):
    return bool(
        user.is_authenticated
        and (
            user == project.created_by
            or user == project.advisor
            or _is_platform_staff(user)
        )
    )


def _can_add_project_update(user, project):
    return bool(
        user.is_authenticated and (
            user == project.created_by or user == project.advisor or project.team.filter(pk=user.pk).exists()
        )
    )


def _record_project_view(request, project):
    """Count at most one view per project and privacy-safe identity each day."""

    if request.user.is_authenticated:
        identity = f'user:{request.user.pk}'
        viewer = request.user
    else:
        if not request.session.session_key:
            request.session.create()
        identity = f'session:{request.session.session_key}'
        viewer = None
    date_bucket = timezone.localdate()
    digest = hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        f'{identity}:{date_bucket.isoformat()}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    ProjectView.objects.get_or_create(
        project=project,
        session_hash=digest,
        date_bucket=date_bucket,
        defaults={'viewer': viewer},
    )

def get_student_users():
    return User.objects.filter(
        Q(profile__user_type__in={'student', 'staff_student'})
    ).distinct()


@login_required
def team_member_search(request):
    """Return only non-sensitive public fields needed by the team picker."""
    if is_rate_limited(request, scope='team-member-search', limit=60, window_seconds=60):
        return JsonResponse({'results': [], 'error': 'Çok fazla arama yapıldı.'}, status=429)
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})
    users = User.objects.filter(
        is_active=True,
        profile__user_type='student',
    ).exclude(pk=request.user.pk).filter(
        Q(first_name__icontains=query)
        | Q(last_name__icontains=query)
        | Q(username__icontains=query)
    ).select_related('profile').order_by('first_name', 'last_name', 'pk')[:10]
    return JsonResponse({'results': [
        {
            'id': user.pk,
            'name': user.get_full_name().strip() or user.username,
            'role': user.profile.get_user_type_display(),
            'avatar': user.profile.profile_picture.url if user.profile.profile_picture else '',
        }
        for user in users
    ]})


def team_list(request):
    teams = Team.objects.select_related('leader').prefetch_related(
        'technologies', 'work_areas', 'membership_records__user'
    ).annotate(
        member_count=Count('membership_records', distinct=True),
        active_project_count=Count(
            'projects', filter=Q(projects__development_status__in=['planning', 'in_progress']), distinct=True
        ),
    )
    query = request.GET.get('q', '').strip()
    recruitment = request.GET.get('recruitment', '')
    active_project = request.GET.get('active_project', '')
    technology = request.GET.get('technology', '')
    work_area = request.GET.get('work_area', '')
    sort = request.GET.get('sort', 'name')
    if query:
        teams = teams.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if recruitment == 'open':
        teams = teams.filter(recruitment_open=True)
    if active_project == 'yes':
        teams = teams.filter(active_project_count__gt=0)
    if technology:
        teams = teams.filter(technologies=technology)
    if work_area:
        teams = teams.filter(work_areas=work_area)
    orderings = {'name': 'name', 'newest': '-created_at', 'members': '-member_count', 'projects': '-active_project_count'}
    teams = teams.distinct().order_by(orderings.get(sort, 'name'), 'name')
    return render(request, 'projects/team_list.html', {
        'teams': teams, 'technologies': Technology.objects.filter(is_active=True),
        'work_areas': ProjectCategory.objects.filter(is_active=True),
        'selected': {'q': query, 'recruitment': recruitment, 'active_project': active_project,
                     'technology': technology, 'work_area': work_area, 'sort': sort},
    })


def team_detail(request, slug):
    team = get_object_or_404(
        Team.objects.select_related('leader').prefetch_related(
            'technologies', 'work_areas', 'membership_records__user__profile',
            'open_roles__required_technologies', 'projects__project_type',
        ), slug=slug,
    )
    projects = team.projects.filter(visibility='public', approval_status='approved')
    return render(request, 'projects/team_detail.html', {
        'team': team,
        'active_projects': projects.filter(development_status__in=['idea', 'planning', 'in_progress', 'on_hold']),
        'completed_projects': projects.filter(development_status='completed'),
        'invite_form': TeamInviteForm(team=team) if request.user.is_authenticated and request.user == team.leader else None,
        'role_form': TeamOpenRoleForm() if request.user.is_authenticated and request.user == team.leader else None,
        'can_disband': can_disband_team(request.user, team),
        'is_team_leader': request.user.is_authenticated and request.user == team.leader,
    })


@login_required
def team_create(request):
    ensure_full_participation_account(request.user)
    form = TeamForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        team = create_team(leader=request.user, form=form, request=request)
        messages.success(request, 'Ekip oluşturuldu; ekip lideri olarak üyeliğiniz kaydedildi.')
        return redirect(team.get_absolute_url())
    return render(request, 'projects/team_form.html', {'form': form})


@login_required
@require_POST
def team_invite(request, slug):
    team = get_object_or_404(Team, slug=slug)
    form = TeamInviteForm(request.POST, team=team)
    if form.is_valid():
        try:
            invite_user(
                team=team, inviter=request.user, invited_user=form.cleaned_data['invited_user'],
                proposed_role=form.cleaned_data['proposed_role'], request=request,
            )
            messages.success(request, 'Ekip daveti gönderildi.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
    else:
        messages.error(request, 'Davet bilgilerini kontrol edin.')
    return redirect(team.get_absolute_url())


@login_required
def team_invitations(request):
    invitations = request.user.team_invitations.select_related('team', 'invited_by').order_by('-created_at')
    return render(request, 'projects/team_invitations.html', {'invitations': invitations})


@login_required
@require_POST
def team_invitation_respond(request, invitation_id):
    ensure_full_participation_account(request.user)
    try:
        respond_to_invitation(
            invitation_id=invitation_id, user=request.user,
            accept=request.POST.get('decision') == 'accept', request=request,
        )
        messages.success(request, 'Davet yanıtınız kaydedildi.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('projects:team_invitations')


@login_required
@require_POST
def team_invitation_cancel(request, invitation_id):
    invitation = get_object_or_404(TeamInvitation.objects.select_related('team'), pk=invitation_id)
    team_url = invitation.team.get_absolute_url()
    try:
        cancel_invitation(invitation_id=invitation_id, user=request.user, request=request)
        messages.success(request, 'Davet iptal edildi.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect(team_url)


@login_required
@require_POST
def team_open_role_add(request, slug):
    team = get_object_or_404(Team, slug=slug)
    if team.leader_id != request.user.pk:
        raise PermissionDenied
    form = TeamOpenRoleForm(request.POST)
    if form.is_valid():
        role = form.save(commit=False)
        role.team = team
        role.save()
        form.save_m2m()
        messages.success(request, 'Açık ekip rolü eklendi.')
    else:
        messages.error(request, 'Açık rol bilgilerini kontrol edin.')
    return redirect(team.get_absolute_url())


@login_required
@require_POST
def team_disband(request, slug):
    team = get_object_or_404(Team, slug=slug)
    if not can_disband_team(request.user, team):
        raise PermissionDenied
    if request.POST.get('team_name', '').strip() != team.name:
        messages.error(request, 'Ekip adı doğrulaması eşleşmedi. Ekip dağıtılmadı.')
        return redirect(team.get_absolute_url())
    team_name = disband_team(team=team, actor=request.user, request=request)
    messages.success(request, f'{team_name} ekibi dağıtıldı. Bağlı projeler korunarak ekip bağlantıları kaldırıldı.')
    return redirect('projects:team_list')

# Create your views here.

def project_list(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    technology_id = request.GET.get('technology', '')
    status = request.GET.get('status', '')
    project_type_id = request.GET.get('type', '')
    source = request.GET.get('source', '')
    program_id = request.GET.get('program', '')
    sort = request.GET.get('sort', 'newest')
    offset = _safe_offset(request)
    
    projects = Project.objects.select_related('project_type', 'created_by', 'advisor').prefetch_related(
        'categories', 'technologies', 'media', 'program_participations__program'
    ).all()
    
    # Check if user is authenticated and get user type
    user = request.user if request.user.is_authenticated else None
    user_type = _user_type(user) if user else None
    
    # Staff can moderate everything. Everyone else sees public approved work plus
    # projects they directly participate in.
    if not (user and _is_platform_staff(user)):
        if user and user.is_authenticated:
            projects = projects.filter(
                Q(visibility='public', approval_status='approved') |
                Q(team=user) |
                Q(created_by=user) |
                Q(advisor=user)
            ).distinct()
        else:
            projects = projects.filter(visibility='public', approval_status='approved')
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category_id:
        projects = projects.filter(categories__id=category_id)
    if technology_id:
        projects = projects.filter(technologies__id=technology_id)
    if status:
        projects = projects.filter(development_status=status)
    if project_type_id:
        projects = projects.filter(project_type_id=project_type_id)
    if source:
        projects = projects.filter(creation_source=source)
    if program_id:
        projects = projects.filter(program_participations__program_id=program_id)
    
    projects = projects.annotate(like_count=Count('likes', distinct=True))
    projects = projects.order_by('-like_count', '-created_at') if sort == 'liked' else projects.order_by('-created_at')
    page_size = PAGE_SIZE
    
    total_count = projects.distinct().count()
    projects = projects.distinct()[offset:offset + page_size]
    has_more = offset + page_size < total_count

    active_filter_labels = []
    if query:
        active_filter_labels.append(f'Arama: {query[:60]}')
    if project_type_id:
        label = ProjectType.objects.filter(pk=project_type_id).values_list('name', flat=True).first()
        if label:
            active_filter_labels.append(f'Tür: {label}')
    if technology_id:
        label = Technology.objects.filter(pk=technology_id).values_list('name', flat=True).first()
        if label:
            active_filter_labels.append(f'Teknoloji: {label}')
    if category_id:
        label = ProjectCategory.objects.filter(pk=category_id).values_list('name', flat=True).first()
        if label:
            active_filter_labels.append(f'Kategori: {label}')
    for value, label in Project.DEVELOPMENT_STATUS_CHOICES:
        if status == value:
            active_filter_labels.append(f'Durum: {label}')
    for value, label in Project.CREATION_SOURCE_CHOICES:
        if source == value:
            active_filter_labels.append(f'Kaynak: {label}')
    if program_id:
        label = ProjectProgram.objects.filter(pk=program_id).values_list('name', flat=True).first()
        if label:
            active_filter_labels.append(f'Program: {label}')
    
    context = {
        'projects': projects,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
        'statuses': Project.DEVELOPMENT_STATUS_CHOICES,
        'project_types': ProjectType.objects.filter(is_active=True),
        'creation_sources': [choice for choice in Project.CREATION_SOURCE_CHOICES if choice[0] != 'LEGACY'],
        'programs': ProjectProgram.objects.filter(is_active=True),
        'selected_category': category_id,
        'selected_technology': technology_id,
        'selected_status': status,
        'selected_type': project_type_id,
        'selected_source': source,
        'selected_program': program_id,
        'selected_sort': sort,
        'has_more': has_more,
        'next_offset': offset + page_size,
        'total_count': total_count,
        'active_filter_labels': active_filter_labels,
        'has_active_filters': bool(active_filter_labels),
        'is_authenticated': request.user.is_authenticated,  # Pass to template
    }
    return render(request, 'projects/project_list.html', context)


def project_load_more(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    technology_id = request.GET.get('technology', '')
    status = request.GET.get('status', '')
    project_type_id = request.GET.get('type', '')
    source = request.GET.get('source', '')
    program_id = request.GET.get('program', '')
    sort = request.GET.get('sort', 'newest')
    offset = _safe_offset(request)
    limit = PAGE_SIZE
    
    projects = Project.objects.select_related('project_type', 'created_by', 'advisor').prefetch_related(
        'categories', 'technologies', 'media', 'program_participations__program'
    ).all()
    
    # Check if user is authenticated and get user type
    user = request.user if request.user.is_authenticated else None
    user_type = _user_type(user) if user else None
    
    if not (user and _is_platform_staff(user)):
        if user and user.is_authenticated:
            projects = projects.filter(
                Q(visibility='public', approval_status='approved') |
                Q(team=user) |
                Q(created_by=user) |
                Q(advisor=user)
            ).distinct()
        else:
            projects = projects.filter(visibility='public', approval_status='approved')
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category_id:
        projects = projects.filter(categories__id=category_id)
    if technology_id:
        projects = projects.filter(technologies__id=technology_id)
    if status:
        projects = projects.filter(development_status=status)
    if project_type_id:
        projects = projects.filter(project_type_id=project_type_id)
    if source:
        projects = projects.filter(creation_source=source)
    if program_id:
        projects = projects.filter(program_participations__program_id=program_id)
    
    projects = projects.annotate(like_count=Count('likes', distinct=True))
    projects = projects.order_by('-like_count', '-created_at') if sort == 'liked' else projects.order_by('-created_at')
    total_count = projects.distinct().count()
    projects = projects.distinct()[offset:offset + limit]
    has_more = offset + limit < total_count
    
    html = render_to_string('projects/partials/project_item.html', {'projects': projects})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + limit
    })


def request_list(request):
    user_type = _user_type(request.user) if request.user.is_authenticated else None
    requests = ProjectRequest.objects.select_related('teacher', 'project_type', 'created_project').prefetch_related(
        'categories', 'technologies'
    )
    scope = request.GET.get('scope', '')
    if _is_django_admin(request.user):
        pass
    elif user_type == 'teacher':
        requests = requests.filter(teacher=request.user)
    elif user_type == 'student':
        if scope == 'applications':
            requests = requests.filter(applications__student=request.user).distinct()
        else:
            requests = requests.filter(Q(status='open') | Q(applications__student=request.user)).distinct()
    else:
        requests = requests.filter(status='open')
    requests = requests.annotate(application_count=Count('applications', distinct=True))
    return render(request, 'projects/request_list.html', {
        'requests': requests,
        'can_create_request': bool(request.user.is_authenticated and (user_type == 'teacher' or _is_django_admin(request.user))),
        'is_student': user_type == 'student',
    })


def request_detail(request, request_id):
    project_request = get_object_or_404(
        ProjectRequest.objects.select_related('teacher', 'project_type', 'created_project').prefetch_related(
            'categories', 'technologies'
        ),
        pk=request_id,
    )
    user_type = _user_type(request.user) if request.user.is_authenticated else None
    own_application = None
    if user_type == 'student':
        own_application = project_request.applications.filter(student=request.user).first()
        if project_request.status != 'open' and own_application is None:
            raise PermissionDenied
    elif request.user.is_authenticated and (_is_django_admin(request.user) or project_request.teacher_id == request.user.id):
        pass
    elif project_request.status != 'open':
        raise PermissionDenied

    return render(request, 'projects/request_detail.html', {
        'project_request': project_request,
        'own_application': own_application,
        'application_form': ProjectRequestApplicationForm(),
    })


@login_required
@require_POST
def request_apply(request, request_id):
    ensure_interactive_account(request.user)
    project_request = get_object_or_404(ProjectRequest, pk=request_id)
    if _user_type(request.user) != 'student' or not request.user.is_active:
        raise PermissionDenied
    if not project_request.accepts_applications:
        messages.error(request, 'Bu proje isteği şu anda başvuru kabul etmiyor.')
        return redirect('projects:request_detail', request_id=project_request.pk)

    form = ProjectRequestApplicationForm(request.POST)
    if form.is_valid():
        if ProjectRequestApplication.objects.filter(
            project_request=project_request,
            student=request.user,
        ).exists():
            messages.error(request, 'Bu proje isteğine daha önce başvurdunuz.')
            return redirect('projects:request_detail', request_id=project_request.pk)
        application = form.save(commit=False)
        application.project_request = project_request
        application.student = request.user
        try:
            with transaction.atomic():
                application.save()
        except IntegrityError:
            messages.error(request, 'Bu proje isteğine daha önce başvurdunuz.')
        else:
            messages.success(request, 'Başvurunuz akademisyene iletildi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('projects:request_detail', request_id=project_request.pk)


@login_required
@require_POST
def request_application_withdraw(request, application_id):
    application = get_object_or_404(
        ProjectRequestApplication,
        pk=application_id,
        student=request.user,
    )
    if application.status != 'pending':
        messages.error(request, 'Yalnızca bekleyen başvurunuzu geri çekebilirsiniz.')
    else:
        from django.utils import timezone
        application.status = 'withdrawn'
        application.withdrawn_at = timezone.now()
        application.save(update_fields=['status', 'withdrawn_at', 'updated_at'])
        messages.success(request, 'Başvurunuz geri çekildi.')
    return redirect('projects:request_detail', request_id=application.project_request_id)


@login_required
def request_applications(request, request_id):
    project_request = get_object_or_404(ProjectRequest.objects.select_related('teacher'), pk=request_id)
    if not (_is_django_admin(request.user) or project_request.teacher_id == request.user.id):
        raise PermissionDenied
    applications = project_request.applications.select_related('student', 'student__profile', 'reviewed_by')
    return render(request, 'projects/request_applications.html', {
        'project_request': project_request,
        'applications': applications,
        'review_form': ApplicationReviewForm(),
    })


@login_required
@require_POST
def request_application_accept(request, application_id):
    form = ApplicationReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Değerlendirme notu geçersiz.')
        return redirect('projects:request_list')
    try:
        project, created = accept_project_request_application(
            application_id=application_id,
            reviewer=request.user,
            review_note=form.cleaned_data['review_note'],
        )
    except ProjectRequestApplication.DoesNotExist:
        messages.error(request, 'Başvuru bulunamadı.')
        return redirect('projects:request_list')
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
        application = ProjectRequestApplication.objects.filter(pk=application_id).first()
        if application:
            return redirect('projects:request_applications', request_id=application.project_request_id)
        return redirect('projects:request_list')
    messages.success(request, 'Başvuru kabul edildi ve proje oluşturuldu.' if created else 'Bu başvuru daha önce kabul edilmişti.')
    return redirect('projects:project_detail', project_id=project.pk)


@login_required
@require_POST
@transaction.atomic
def request_application_reject(request, application_id):
    application = get_object_or_404(
        ProjectRequestApplication.objects.select_for_update().select_related('project_request'),
        pk=application_id,
    )
    if not (_is_django_admin(request.user) or application.project_request.teacher_id == request.user.id):
        raise PermissionDenied
    if application.status != 'pending':
        messages.error(request, 'Yalnızca bekleyen bir başvuru reddedilebilir.')
    else:
        form = ApplicationReviewForm(request.POST)
        if form.is_valid():
            application.mark_reviewed(request.user, 'rejected', form.cleaned_data['review_note'])
            create_notification(
                recipient=application.student,
                actor=request.user,
                notification_type='application_rejected',
                message=f'“{application.project_request.title}” başvurun reddedildi.',
                target_url=f'/projects/requests/{application.project_request_id}/',
            )
            messages.success(request, 'Başvuru reddedildi.')
    return redirect('projects:request_applications', request_id=application.project_request_id)


@login_required
def request_create(request):
    if _user_type(request.user) != 'teacher' and not _is_django_admin(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = RequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.teacher = request.user
            req.save()
            form.save_m2m()
            record_audit_event(
                actor=request.user,
                action='project_request.created',
                target=req,
                request=request,
            )
            messages.success(request, 'Proje isteği başarıyla oluşturuldu.')
            return redirect('projects:request_list')
    else:
        form = RequestForm()
    return render(request, 'projects/request_form.html', {
        'form': form,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
    })


@login_required
def request_edit(request, request_id):
    req = get_object_or_404(ProjectRequest, id=request_id)
    if req.teacher != request.user and not _is_django_admin(request.user):
        messages.error(request, 'Bu isteği düzenleme yetkiniz yok.')
        return redirect('projects:request_list')

    if request.method == 'POST':
        form = RequestForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            messages.success(request, 'Proje isteği başarıyla güncellendi.')
            return redirect('projects:request_list')
    else:
        form = RequestForm(instance=req)
    return render(request, 'projects/request_form.html', {
        'form': form,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
    })


@login_required
@require_POST
def request_delete(request, request_id):
    req = get_object_or_404(ProjectRequest.objects.select_related('teacher'), id=request_id)
    if req.teacher != request.user and not _is_django_admin(request.user):
        messages.error(request, 'Bu isteği silme yetkiniz yok.')
        return redirect('projects:request_list')

    if request.POST.get('confirm_delete') != 'yes':
        messages.error(request, 'İlanı silmek için onay kutusunu işaretlemelisiniz.')
        return redirect('projects:request_detail', request_id=req.pk)

    title = req.title
    teacher = req.teacher
    linked_project_ids = list(req.projects.values_list('pk', flat=True))
    record_audit_event(
        actor=request.user,
        action='project_request.deleted',
        target=req,
        request=request,
        metadata={
            'title': title,
            'teacher_id': req.teacher_id,
            'linked_project_ids': linked_project_ids,
            'application_count': req.applications.count(),
        },
    )
    req.delete()
    if teacher and teacher != request.user:
        create_notification(
            recipient=teacher,
            actor=request.user,
            notification_type='moderation',
            title='Proje ilanı silindi',
            message=f'“{title}” proje ilanı bir yönetici tarafından silindi.',
            target_url=reverse('projects:request_list'),
            force=True,
        )
    messages.success(request, 'Proje ilanı silindi. İlanla bağlantılı projeler korunarak bağlantıları kaldırıldı.')
    if request.POST.get('return_to') == 'dashboard':
        return redirect('dashboard:requests')
    return redirect('projects:request_list')


def _comment_profile_url(author, viewer):
    """Link to an accessible public profile, never the viewer's account page."""
    profile = getattr(author, 'profile', None)
    if not profile or not author.is_active or profile.account_status != 'active':
        return ''
    if author.is_staff or author.is_superuser:
        return ''
    if profile.user_type in {'student', 'staff_student'}:
        if profile.is_portfolio_public or viewer == author:
            return profile.get_absolute_url()
    elif profile.user_type == 'teacher' and profile.show_in_search:
        return f"{reverse('portal:academic_list')}#academic-{profile.pk}"
    elif profile.user_type == 'alumni' and viewer.is_authenticated:
        alumnus = getattr(author, 'alumni', None)
        if alumnus and alumnus.is_show_in_alumni_list:
            return reverse('alumni:alumni_detail', args=[author.username])
    elif profile.user_type in {'visitor', 'approved_member'} and viewer.is_authenticated:
        return reverse('accounts:user_profile', args=[author.pk])
    return ''


def project_detail(request, project_id):
    project = get_object_or_404(
        Project.objects.select_related(
            'project_type', 'created_by', 'advisor', 'project_request'
        ).prefetch_related(
            'team', 'categories', 'technologies', 'media', 'contributions__user',
            'achievements', 'program_participations__program',
        ),
        id=project_id,
    )
    user = request.user
    if not _can_view_project(user, project):
        messages.error(request, 'Bu projeyi görüntüleme yetkiniz bulunmuyor.')
        return redirect('projects:project_list')
    _record_project_view(request, project)
    
    updates = project.updates.all()
    comments = list(project.comments.filter(parent__isnull=True).select_related(
        'author', 'author__profile', 'author__alumni',
    ).prefetch_related(Prefetch(
        'replies', queryset=ProjectComment.objects.select_related('author', 'author__profile', 'author__alumni'),
    )))
    author_urls = {}
    for root_comment in comments:
        for comment in [root_comment, *root_comment.replies.all()]:
            if comment.author_id not in author_urls:
                author_urls[comment.author_id] = _comment_profile_url(comment.author, user)
            comment.author_profile_url = author_urls[comment.author_id]
    
    # Check if user can see feedback (team members, advisor, staff)
    can_see_feedback = False
    feedback_form = None
    feedback_obj = None
    if request.user.is_authenticated:
        is_team_member = project.team.filter(pk=user.pk).exists()
        is_advisor = user == project.advisor
        is_staff_or_teacher = _is_platform_staff(user)
        can_see_feedback = is_team_member or is_advisor or is_staff_or_teacher
        
        try:
            feedback_obj = project.feedback
        except ProjectFeedback.DoesNotExist:
            feedback_obj = None
        
        if is_advisor or is_staff_or_teacher:
            feedback_form = ProjectFeedbackForm(instance=feedback_obj)
    
    # Only show comment form for authenticated users
    if request.user.is_authenticated:
        comment_form = ProjectCommentForm()
    else:
        comment_form = None

    case_study = ProjectCaseStudy.objects.filter(project=project).first()
    all_media = list(project.media.all())
    cover_media = next((item for item in all_media if item.is_cover), None)
    project_logo = next((item for item in all_media if item.media_type == 'project_logo'), None)
    project_gallery = [item for item in all_media if item.media_type == 'image' and not item.is_cover]
    other_media = [item for item in all_media if item.media_type in {'video', 'demo', 'document'}]
    documents = []
    for item in all_media:
        if item.media_type == 'documentation' or (
            item.media_type == 'pitch_deck' and (item.is_public or _can_manage_project(request.user, project))
        ):
            documents.append(item)
    canonical_url = request.build_absolute_uri(project.get_absolute_url())
    context = {
        'project': project,
        'updates': updates,
        'comments': comments,
        'comment_count': project.comments.count(),
        'comment_form': comment_form,
        'feedback_form': feedback_form,
        'feedback_obj': feedback_obj,
        'can_see_feedback': can_see_feedback,
        'case_study': case_study,
        'view_count': project.view_records.count(),
        'save_count': project.saves.count(),
        'like_count': project.likes.count(),
        'is_liked': bool(
            request.user.is_authenticated and project.likes.filter(user=request.user).exists()
        ),
        'is_featured': any(item.is_current for item in project.feature_periods.all()),
        'can_feature_project': bool(
            request.user.is_authenticated and (
                request.user.is_staff or request.user.is_superuser or _user_type(request.user) == 'teacher'
            )
        ),
        'is_saved': bool(
            request.user.is_authenticated
            and project.saves.filter(user=request.user).exists()
        ),
        'can_manage_project': _can_manage_project(request.user, project),
        'can_delete_project': bool(
            request.user.is_authenticated
            and (request.user == project.created_by or _is_platform_staff(request.user))
        ),
        'can_add_project_update': _can_add_project_update(request.user, project),
        'similar_projects': Project.objects.filter(
            project_type=project.project_type,
            visibility='public',
            approval_status='approved',
        ).exclude(pk=project.pk).select_related('project_type')[:3],
        'cover_media': cover_media,
        'project_logo': project_logo,
        'project_gallery': project_gallery,
        'project_media': other_media,
        'project_documents': documents,
        'project_url': canonical_url,
        'canonical_url': canonical_url,
        'meta_title': f'{project.title} | BST Portal',
        'meta_description': (
            (case_study.summary if case_study else '')
            or project.description
            or 'BST Portal proje vitrini'
        )[:160],
        'meta_robots': (
            'index,follow'
            if project.visibility == 'public' and project.approval_status == 'approved'
            else 'noindex,nofollow'
        ),
    }
    return render(request, 'projects/project_detail.html', context)


def project_detail_by_slug(request, slug):
    project = get_object_or_404(Project.objects.only('pk'), slug=slug)
    return project_detail(request, project.pk)


def project_external_redirect(request, project_id, destination):
    project = get_object_or_404(Project.objects.select_related('case_study'), pk=project_id)
    if not _can_view_project(request.user, project):
        raise PermissionDenied
    if destination == 'demo':
        case_study = getattr(project, 'case_study', None)
        target = getattr(case_study, 'demo_url', '') or project.project_link
        event_type = 'demo_click'
    elif destination == 'github':
        repository = ProjectRepository.objects.filter(project=project).first()
        target = repository.repository_url if repository else ''
        event_type = 'github_click'
    else:
        raise Http404
    if not target:
        raise Http404
    try:
        validate_public_website(target)
    except ValidationError as exc:
        raise Http404 from exc
    record_analytics_event(request, event_type=event_type, target=project, succeeded=True)
    return render(request, 'projects/external_link_warning.html', {
        'project': project,
        'target_url': target,
        'target_host': urlsplit(target).hostname,
        'destination': destination,
    })


@require_GET
def project_media_file(request, media_id, disposition):
    if disposition not in {'view', 'download'}:
        raise Http404
    media = get_object_or_404(
        ProjectMedia.objects.select_related('project', 'project__created_by', 'project__advisor'),
        pk=media_id, media_type__in=['pitch_deck', 'documentation'],
    )
    if not _can_view_project(request.user, media.project):
        raise PermissionDenied
    if media.media_type == 'pitch_deck' and not media.is_public and not _can_manage_project(request.user, media.project):
        raise PermissionDenied
    if not media.file:
        raise Http404
    filename = ('yatirimci-sunumu.pdf' if media.media_type == 'pitch_deck' else 'proje-dokumantasyonu.pdf')
    response = FileResponse(
        media.file.open('rb'), as_attachment=disposition == 'download', filename=filename,
        content_type='application/pdf',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store' if not media.is_public else 'private, max-age=300'
    return response


@require_safe
def project_uploaded_media(request, path):
    """Protect direct local media URLs with the owning project's visibility rules."""
    media = get_object_or_404(
        ProjectMedia.objects.select_related('project', 'project__created_by', 'project__advisor'),
        file=f'projects/media/{path}',
    )
    if not _can_view_project(request.user, media.project):
        raise PermissionDenied
    if media.media_type == 'pitch_deck' and not media.is_public and not _can_manage_project(request.user, media.project):
        raise PermissionDenied
    if not media.file:
        raise Http404
    content_type = mimetypes.guess_type(media.file.name)[0] or 'application/octet-stream'
    response = FileResponse(media.file.open('rb'), content_type=content_type)
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    response['X-Content-Type-Options'] = 'nosniff'
    private_asset = media.project.visibility == 'private' or (
        media.media_type == 'pitch_deck' and not media.is_public
    )
    response['Cache-Control'] = 'private, no-store' if private_asset else 'private, max-age=300'
    return response


def _save_project_assets(project, image_form):
    """Persist form uploads in ProjectMedia while keeping one slot per named asset."""
    data = image_form.cleaned_data
    named_assets = [
        ('cover_image', 'cover_image', 'Kapak görseli', True),
        ('project_logo', 'project_logo', 'Proje logosu', False),
        ('documentation', 'documentation', 'Proje dokümantasyonu', False),
    ]
    for field_name, media_type, caption, is_cover in named_assets:
        upload = data.get(field_name)
        if upload:
            ProjectMedia.objects.filter(project=project, media_type=media_type).delete()
            ProjectMedia.objects.create(
                project=project, media_type=media_type, file=upload,
                caption=caption, alt_text=f'{project.title} {caption.casefold()}', is_cover=is_cover,
            )
    pitch_upload = data.get('pitch_deck')
    pitch_public = data.get('pitch_deck_is_public', False)
    pitch = ProjectMedia.objects.filter(project=project, media_type='pitch_deck').first()
    if pitch_upload:
        if pitch:
            pitch.delete()
        ProjectMedia.objects.create(
            project=project, media_type='pitch_deck', file=pitch_upload,
            caption='Yatırımcı sunumu', is_public=pitch_public,
        )
    elif pitch and pitch.is_public != pitch_public:
        pitch.is_public = pitch_public
        pitch.save(update_fields=['is_public', 'updated_at'])

    images = data.get('images', [])
    requested_cover = data.get('cover_index')
    has_cover = project.media.filter(is_cover=True).exists()
    max_order = project.media.aggregate(max_order=Max('order'))['max_order']
    start_order = (max_order + 1) if max_order is not None else 0
    for index, image in enumerate(images):
        make_cover = not data.get('cover_image') and (index == requested_cover or (not has_cover and index == 0))
        ProjectMedia.objects.create(
            project=project, media_type='image', file=image,
            alt_text=f'{project.title} proje görseli {start_order + index + 1}',
            order=start_order + index, is_cover=make_cover,
        )
        has_cover = has_cover or make_cover

@login_required
def project_create(request):
    ensure_full_participation_account(request.user)
    if request.method == 'POST':
        form = ProjectForm(request.POST, request.FILES, current_user=request.user)
        repository_form = ProjectRepositoryForm(request.POST)
        image_form = ProjectImageUploadForm(request.POST, request.FILES)
        if form.is_valid() and repository_form.is_valid() and image_form.is_valid():
            with transaction.atomic():
                project = form.save(commit=False)
                project.created_by = request.user
                if project.project_type.requires_approval:
                    project.approval_status = 'pending'
                    project.status = 'in_review'
                else:
                    project.approval_status = 'approved'
                    project.status = 'approved'
                if project.development_status == 'in_progress':
                    project.status = 'in_progress'
                elif project.development_status == 'completed':
                    project.status = 'completed'
                project.is_private = project.visibility != 'public'
                project.save()
                form.save_m2m()
                project.team.add(request.user)
                repository_path = repository_form.cleaned_data.get('repository_path', '').strip()
                if repository_path:
                    repository = repository_form.save(commit=False)
                    repository.project = project
                    repository.save()
                _save_project_assets(project, image_form)
                record_audit_event(
                    actor=request.user,
                    action='project.created',
                    target=project,
                    request=request,
                )

            messages.success(request, 'Proje başarıyla oluşturuldu.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        form = ProjectForm(current_user=request.user)
        repository_form = ProjectRepositoryForm()
        image_form = ProjectImageUploadForm()
    team_members = get_student_users()
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'projects/project_form.html', {
        'form': form,
        'action': 'create',
        'team_members': team_members,
        'categories': categories,
        'technologies': technologies,
        'image_form': image_form,
        'repository_form': repository_form,
        'existing_image_media': [],
        'has_existing_cover': False,
    })

@login_required
def project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user != project.created_by and request.user != project.advisor and not _is_platform_staff(request.user):
        messages.error(request, 'Bu projeyi düzenleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    repository = ProjectRepository.objects.filter(project=project).first()
    if request.method == 'POST':
        form = ProjectForm(request.POST, request.FILES, instance=project, current_user=request.user)
        repository_form = ProjectRepositoryForm(request.POST, instance=repository)
        image_form = ProjectImageUploadForm(request.POST, request.FILES)
        if form.is_valid() and repository_form.is_valid() and image_form.is_valid():
            with transaction.atomic():
                updated_project = form.save(commit=False)
                updated_project.is_private = updated_project.visibility != 'public'
                if updated_project.development_status == 'in_progress':
                    updated_project.status = 'in_progress'
                elif updated_project.development_status == 'completed':
                    updated_project.status = 'completed'
                updated_project.save()
                form.save_m2m()

                repository_path = repository_form.cleaned_data.get('repository_path', '').strip()
                if repository_path:
                    updated_repository = repository_form.save(commit=False)
                    updated_repository.project = updated_project
                    updated_repository.save()
                elif repository:
                    repository.delete()

                _save_project_assets(updated_project, image_form)

                record_audit_event(
                    actor=request.user,
                    action='project.updated',
                    target=updated_project,
                    request=request,
                )
            messages.success(request, 'Proje başarıyla güncellendi.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        form = ProjectForm(instance=project, current_user=request.user)
        repository_form = ProjectRepositoryForm(instance=repository)
        existing_pitch = project.media.filter(media_type='pitch_deck').first()
        image_form = ProjectImageUploadForm(initial={
            'pitch_deck_is_public': bool(existing_pitch and existing_pitch.is_public),
        })

    existing_image_media = project.media.filter(media_type__in=['image', 'cover_image', 'project_logo'])
    existing_documents = project.media.filter(media_type__in=['pitch_deck', 'documentation'])
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'projects/project_form.html', {
        'form': form,
        'action': 'update',
        'team_members': get_student_users(),
        'categories': categories,
        'technologies': technologies,
        'repository_form': repository_form,
        'image_form': image_form,
        'existing_image_media': existing_image_media,
        'has_existing_cover': existing_image_media.filter(is_cover=True).exists(),
        'existing_documents': existing_documents,
    })


@login_required
@require_POST
def project_delete(request, project_id):
    project = get_object_or_404(Project.objects.select_related('created_by'), pk=project_id)
    if request.user != project.created_by and not _is_platform_staff(request.user):
        raise PermissionDenied

    if request.POST.get('confirm_delete') != 'yes':
        messages.error(request, 'Projeyi silmek için işlemi açıkça onaylamalısınız.')
        return redirect('projects:project_detail', project_id=project.pk)

    title = project.title
    with transaction.atomic():
        record_audit_event(
            actor=request.user,
            action='project.deleted',
            target=project,
            request=request,
            metadata={
                'title': title,
                'created_by_id': project.created_by_id,
            },
        )
        project.delete()

    messages.success(request, f'“{title}” projesi kalıcı olarak silindi.')
    return redirect('projects:project_list')


@login_required
@require_POST
def toggle_project_save(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_view_project(request.user, project):
        raise PermissionDenied
    saved, created = ProjectSave.objects.get_or_create(project=project, user=request.user)
    if created:
        messages.success(request, 'Proje kaydedilenlere eklendi.')
    else:
        saved.delete()
        messages.success(request, 'Proje kaydedilenlerden çıkarıldı.')
    return redirect('projects:project_detail', project_id=project.pk)


@login_required
def saved_projects(request):
    saved = ProjectSave.objects.filter(user=request.user).select_related(
        'project', 'project__project_type', 'project__created_by'
    ).prefetch_related('project__technologies')
    visible_saved = [item for item in saved if _can_view_project(request.user, item.project)]
    return render(request, 'projects/saved_projects.html', {'saved_projects': visible_saved})


@login_required
def project_showcase_manage(request, project_id):
    project = get_object_or_404(Project.objects.select_related('created_by', 'advisor'), pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    case_study = ProjectCaseStudy.objects.filter(project=project).first()
    if request.method == 'POST':
        case_study_form = ProjectCaseStudyForm(request.POST, instance=case_study)
        if case_study_form.is_valid():
            case_study = case_study_form.save(commit=False)
            case_study.project = project
            case_study.save()
            messages.success(request, 'Vaka çalışması güncellendi.')
            return redirect('projects:project_showcase_manage', project_id=project.pk)
    else:
        case_study_form = ProjectCaseStudyForm(instance=case_study)
    writing_suggestion = None
    suggestion_id = request.GET.get('suggestion', '')
    if suggestion_id.isdigit():
        writing_suggestion = ProjectWritingSuggestion.objects.filter(
            pk=suggestion_id,
            project=project,
            status='preview',
        ).first()
    return render(request, 'projects/showcase_manage.html', {
        'project': project,
        'case_study_form': case_study_form,
        'media_form': ProjectMediaForm(),
        'contribution_form': ProjectContributionForm(project=project),
        'achievement_form': ProjectAchievementForm(),
        'media_items': project.media.all(),
        'contributions': project.contributions.select_related('user'),
        'achievements': project.achievements.all(),
        'repository': ProjectRepository.objects.filter(project=project).first(),
        'repository_form': ProjectRepositoryForm(
            instance=ProjectRepository.objects.filter(project=project).first()
        ),
        'writing_suggestion': writing_suggestion,
    })


@login_required
@require_POST
def project_writing_generate(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    if is_rate_limited(request, scope='project-writing', limit=5, window_seconds=300):
        messages.error(request, 'Çok fazla öneri istendi. Lütfen birkaç dakika sonra yeniden deneyin.')
        return redirect('projects:project_showcase_manage', project_id=project.pk)

    source_text = request.POST.get('source_text', '').strip()
    if len(source_text) < 30:
        messages.error(request, 'Öneri oluşturmak için en az 30 karakterlik proje metni girin.')
        return redirect('projects:project_showcase_manage', project_id=project.pk)
    if len(source_text) > 8000:
        messages.error(request, 'Proje metni en fazla 8000 karakter olabilir.')
        return redirect('projects:project_showcase_manage', project_id=project.pk)

    from ai_assistant.project_writing import generate_project_writing_suggestion
    try:
        fields = generate_project_writing_suggestion(source_text)
    except (ImproperlyConfigured, ValidationError) as exc:
        messages.error(request, str(exc))
        return redirect('projects:project_showcase_manage', project_id=project.pk)
    except Exception:
        logger.exception('Proje yazım önerisi üretilemedi.')
        messages.error(request, 'AI servisine şu anda ulaşılamıyor. Metniniz değiştirilmedi.')
        return redirect('projects:project_showcase_manage', project_id=project.pk)

    suggestion = ProjectWritingSuggestion.objects.create(
        project=project,
        created_by=request.user,
        original_text=source_text,
        suggested_fields=fields,
    )
    record_audit_event(actor=request.user, action='project.ai_writing_previewed', target=project, request=request)
    return redirect(f'{reverse("projects:project_showcase_manage", kwargs={"project_id": project.pk})}?suggestion={suggestion.pk}#ai-writing')


@login_required
@require_POST
def project_writing_apply(request, suggestion_id):
    with transaction.atomic():
        suggestion = get_object_or_404(
            ProjectWritingSuggestion.objects.select_for_update().select_related('project'),
            pk=suggestion_id,
            status='preview',
        )
        project = suggestion.project
        if not _can_manage_project(request.user, project):
            raise PermissionDenied
        allowed = {'problem', 'solution', 'architecture', 'measurable_results', 'future_developments'}
        selected = allowed & set(request.POST.getlist('fields'))
        if not selected:
            messages.error(request, 'Uygulamak için en az bir alan seçin.')
            return redirect(f'{reverse("projects:project_showcase_manage", kwargs={"project_id": project.pk})}?suggestion={suggestion.pk}#ai-writing')
        case_study, _ = ProjectCaseStudy.objects.get_or_create(project=project)
        changed = []
        for field in selected:
            value = suggestion.suggested_fields.get(field, '')
            if isinstance(value, str) and value.strip():
                setattr(case_study, field, value.strip()[:5000])
                changed.append(field)
        if not changed:
            messages.error(request, 'Seçilen alanlarda uygulanabilir öneri bulunmuyor.')
            return redirect(f'{reverse("projects:project_showcase_manage", kwargs={"project_id": project.pk})}?suggestion={suggestion.pk}#ai-writing')
        case_study.save(update_fields=changed + ['updated_at'])
        suggestion.status = 'applied'
        suggestion.applied_at = timezone.now()
        suggestion.save(update_fields=['status', 'applied_at'])
        record_audit_event(actor=request.user, action='project.ai_writing_applied', target=project, request=request)
    messages.success(request, 'Seçtiğiniz AI önerileri vaka çalışmasına uygulandı; proje yayın durumu değiştirilmedi.')
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_writing_reject(request, suggestion_id):
    suggestion = get_object_or_404(ProjectWritingSuggestion.objects.select_related('project'), pk=suggestion_id, status='preview')
    if not _can_manage_project(request.user, suggestion.project):
        raise PermissionDenied
    suggestion.status = 'rejected'
    suggestion.save(update_fields=['status'])
    messages.info(request, 'AI önerisi uygulanmadan reddedildi.')
    return redirect('projects:project_showcase_manage', project_id=suggestion.project_id)


@login_required
def project_matches(request, project_id):
    project = get_object_or_404(
        Project.objects.select_related('created_by', 'advisor').prefetch_related('technologies', 'categories', 'team'),
        pk=project_id,
    )
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    from .matching import rank_all_matches
    return render(request, 'projects/matches.html', {'project': project, **rank_all_matches(project)})


@login_required
@require_POST
def project_repository_save(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    repository = ProjectRepository.objects.filter(project=project).first()
    form = ProjectRepositoryForm(request.POST, instance=repository)
    if form.is_valid():
        repository = form.save(commit=False)
        repository.project = project
        repository.save()
        messages.success(request, 'GitHub repository bağlantısı kaydedildi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_repository_delete(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    ProjectRepository.objects.filter(project=project).delete()
    messages.success(request, 'GitHub repository bağlantısı kaldırıldı.')
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_media_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    form = ProjectMediaForm(request.POST, request.FILES)
    if form.is_valid():
        media = form.save(commit=False)
        media.project = project
        media.save()
        messages.success(request, 'Proje medyası eklendi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_media_delete(request, media_id):
    media = get_object_or_404(ProjectMedia.objects.select_related('project'), pk=media_id)
    if not _can_manage_project(request.user, media.project):
        raise PermissionDenied
    project_id = media.project_id
    was_cover = media.is_cover
    with transaction.atomic():
        media.delete()
        if was_cover:
            replacement = ProjectMedia.objects.filter(
                project_id=project_id, media_type='image'
            ).order_by('order', 'created_at').first()
            if replacement:
                replacement.is_cover = True
                replacement.save(update_fields=['is_cover', 'updated_at'])
        record_audit_event(
            actor=request.user,
            action='project.media_deleted',
            target=media.project,
            request=request,
        )
    messages.success(request, 'Proje medyası silindi.')
    if request.POST.get('return_to') == 'project_edit':
        return redirect('projects:project_update', project_id=project_id)
    return redirect('projects:project_showcase_manage', project_id=project_id)


@login_required
@require_POST
def project_images_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    form = ProjectImageUploadForm(request.POST, request.FILES)
    if form.is_valid():
        with transaction.atomic():
            start_order = project.media.count()
            has_cover = project.media.filter(is_cover=True).exists()
            requested_cover = form.cleaned_data.get('cover_index')
            for index, image in enumerate(form.cleaned_data['images']):
                make_cover = index == requested_cover or (not has_cover and index == 0)
                ProjectMedia.objects.create(
                    project=project, media_type='image', file=image,
                    alt_text=f'{project.title} proje görseli {start_order + index + 1}',
                    order=start_order + index, is_cover=make_cover,
                )
                has_cover = has_cover or make_cover
        messages.success(request, 'Proje görselleri eklendi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_media_set_cover(request, media_id):
    media = get_object_or_404(ProjectMedia.objects.select_related('project'), pk=media_id, media_type='image')
    if not _can_manage_project(request.user, media.project):
        raise PermissionDenied
    media.is_cover = True
    media.save(update_fields=['is_cover', 'updated_at'])
    record_audit_event(
        actor=request.user,
        action='project.cover_updated',
        target=media.project,
        request=request,
    )
    messages.success(request, 'Proje kapağı güncellendi.')
    if request.POST.get('return_to') == 'project_edit':
        return redirect('projects:project_update', project_id=media.project_id)
    return redirect('projects:project_showcase_manage', project_id=media.project_id)


@login_required
@require_POST
def toggle_project_like(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_view_project(request.user, project):
        raise PermissionDenied
    like, created = ProjectLike.objects.get_or_create(project=project, user=request.user)
    if not created:
        like.delete()
    count = project.likes.count()
    if created and count in {10, 25, 50, 100, 250, 500}:
        create_notification(
            recipient=project.created_by,
            actor=request.user if request.user.pk != project.created_by_id else None,
            notification_type='project_like_milestone',
            title='Projeniz ilgi görüyor', message=f'{project.title} projeniz {count} beğeniye ulaştı.',
            target_url=project.get_absolute_url(), dedupe_key=f'project-like:{project.pk}:{count}',
        )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'liked': created, 'count': count})
    return redirect(project.get_absolute_url())


@login_required
@require_POST
def project_feature_toggle(request, project_id):
    if not (request.user.is_staff or request.user.is_superuser or _user_type(request.user) == 'teacher'):
        raise PermissionDenied
    project = get_object_or_404(Project, pk=project_id, visibility='public', approval_status='approved')
    active = next((item for item in project.feature_periods.all() if item.is_current), None)
    if active:
        active.is_active = False
        active.save(update_fields=['is_active', 'updated_at'])
        action = 'project.unfeatured'
        message = 'Proje öne çıkanlardan kaldırıldı.'
    else:
        feature = ProjectFeature.objects.create(
            project=project, selected_by=request.user,
            description=request.POST.get('description', '').strip(),
        )
        create_notification(
            recipient=project.created_by, actor=request.user, notification_type='project_featured',
            title='Projeniz öne çıkarıldı', message=f'{project.title} projeniz öne çıkan projelere eklendi.',
            target_url=project.get_absolute_url(), dedupe_key=f'project-feature:{feature.pk}',
        )
        action = 'project.featured'
        message = 'Proje öne çıkarıldı.'
    record_audit_event(actor=request.user, action=action, target=project, request=request)
    messages.success(request, message)
    return redirect(project.get_absolute_url())


@login_required
@require_POST
def project_contribution_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    form = ProjectContributionForm(request.POST, project=project)
    if form.is_valid():
        contribution = form.save(commit=False)
        contribution.project = project
        try:
            with transaction.atomic():
                contribution.save()
        except IntegrityError:
            messages.error(request, 'Bu ekip üyesi için zaten bir katkı kaydı var.')
        else:
            messages.success(request, 'Katkı kaydı eklendi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_contribution_verify(request, contribution_id):
    contribution = get_object_or_404(
        ProjectContribution.objects.select_related('project'),
        pk=contribution_id,
    )
    project = contribution.project
    can_verify_owner = request.user == project.created_by or _is_platform_staff(request.user)
    can_verify_advisor = request.user == project.advisor or _is_platform_staff(request.user)
    if not (can_verify_owner or can_verify_advisor):
        raise PermissionDenied
    if can_verify_owner:
        contribution.verified_by_owner = True
    if can_verify_advisor:
        contribution.verified_by_advisor = True
    if contribution.is_verified:
        contribution.verified_at = timezone.now()
    contribution.save(update_fields=['verified_by_owner', 'verified_by_advisor', 'verified_at', 'updated_at'])
    messages.success(request, 'Katkı doğrulaması güncellendi.')
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_contribution_delete(request, contribution_id):
    contribution = get_object_or_404(
        ProjectContribution.objects.select_related('project'),
        pk=contribution_id,
    )
    if not _can_manage_project(request.user, contribution.project):
        raise PermissionDenied
    project_id = contribution.project_id
    contribution.delete()
    messages.success(request, 'Katkı kaydı silindi.')
    return redirect('projects:project_showcase_manage', project_id=project_id)


@login_required
@require_POST
def project_achievement_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_manage_project(request.user, project):
        raise PermissionDenied
    form = ProjectAchievementForm(request.POST, request.FILES)
    if form.is_valid():
        achievement = form.save(commit=False)
        achievement.project = project
        achievement.save()
        messages.success(request, 'Başarı kaydı eklendi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('projects:project_showcase_manage', project_id=project.pk)


@login_required
@require_POST
def project_achievement_delete(request, achievement_id):
    achievement = get_object_or_404(ProjectAchievement.objects.select_related('project'), pk=achievement_id)
    if not _can_manage_project(request.user, achievement.project):
        raise PermissionDenied
    project_id = achievement.project_id
    achievement.delete()
    messages.success(request, 'Başarı kaydı silindi.')
    return redirect('projects:project_showcase_manage', project_id=project_id)

@login_required
@require_POST
def add_project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    # Check if user is creator, advisor, or team member
    is_team_member = request.user in project.team.all()
    if request.user != project.created_by and request.user != project.advisor and not is_team_member:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Proje güncellemesi ekleme yetkiniz yok.'})
        messages.error(request, 'Proje güncellemesi ekleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    form = ProjectUpdateForm(request.POST)
    if form.is_valid():
            update = form.save(commit=False)
            update.project = project
            update.created_by = request.user
            update.save()
            recipients = {
                save.user_id: save.user
                for save in project.saves.select_related('user')
                if save.user_id != request.user.id
            }
            for recipient in recipients.values():
                create_notification(
                    recipient=recipient,
                    actor=request.user,
                    notification_type='project_update',
                    message=f'“{project.title}” projesine yeni bir güncelleme eklendi.',
                    target_url=project.get_absolute_url(),
                )
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            
            messages.success(request, 'Proje güncellemesi başarıyla eklendi.')
            return redirect('projects:project_detail', project_id=project.id)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        errors = {field: values[0] for field, values in form.errors.items() if values}
        return JsonResponse({'success': False, 'error': 'Form doğrulama hatası', 'errors': errors}, status=400)
    messages.error(request, 'Güncelleme kaydedilemedi. Alanları kontrol edin.')
    return redirect('projects:project_detail', project_id=project.id)

@login_required
@require_POST
def add_comment(request, project_id):
    ensure_interactive_account(request.user)
    project = get_object_or_404(Project, id=project_id)
    if not _can_view_project(request.user, project):
        messages.error(request, 'Bu projeye yorum yapma yetkiniz yok.')
        return redirect('projects:project_list')
    form = ProjectCommentForm(request.POST)
    parent = None
    if request.POST.get('parent_id'):
        try:
            parent_id = int(request.POST['parent_id'])
        except (TypeError, ValueError):
            raise Http404
        parent = get_object_or_404(
            ProjectComment, pk=parent_id, project=project, parent__isnull=True,
        )
    if form.is_valid():
        comment = form.save(commit=False)
        comment.project = project
        comment.author = request.user
        comment.parent = parent
        comment.save()
        create_notification(
            recipient=project.created_by,
            actor=request.user,
            notification_type='project_comment',
            message=f'“{project.title}” projen için yeni bir yorum var.',
            target_url=f'{project.get_absolute_url()}#comment-{comment.pk}',
        )
        if parent and parent.author_id != project.created_by_id:
            create_notification(
                recipient=parent.author, actor=request.user,
                notification_type='project_comment',
                title='Yorumuna yanıt geldi',
                message=f'“{project.title}” projesindeki yorumuna yanıt verildi.',
                target_url=f'{project.get_absolute_url()}#comment-{comment.pk}',
            )
        messages.success(request, 'Yanıtınız eklendi.' if parent else 'Yorumunuz başarıyla eklendi.')
        return redirect(f'{project.get_absolute_url()}#comment-{comment.pk}')
    else:
        messages.error(request, 'Yorum kaydedilemedi. Metin 2–2000 karakter arasında olmalıdır.')
    return redirect('projects:project_detail', project_id=project.id)


@login_required
def edit_comment(request, comment_id):
    comment = get_object_or_404(ProjectComment, id=comment_id)
    
    # Check if user can edit this comment
    if request.user != comment.author:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Bu yorumu düzenleme yetkiniz yok.'})
        messages.error(request, 'Bu yorumu düzenleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=comment.project.id)
    
    if request.method == 'POST':
        form = ProjectCommentForm(request.POST, instance=comment)
        if form.is_valid():
            form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'content': comment.content})
            messages.success(request, 'Yorumunuz başarıyla güncellendi.')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {}
                for field, field_errors in form.errors.items():
                    errors[field] = field_errors[0] if field_errors else 'Bu alan geçersiz.'
                return JsonResponse({'success': False, 'error': 'Form doğrulama hatası', 'errors': errors})
    else:
        form = ProjectCommentForm(instance=comment)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'content': comment.content})
    
    return redirect('projects:project_detail', project_id=comment.project.id)


@login_required
@require_POST
def delete_comment(request, comment_id):
    comment = get_object_or_404(ProjectComment, id=comment_id)
    project_id = comment.project.id
    
    # Check if user can delete this comment
    if request.user != comment.author and not _is_platform_staff(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Bu yorumu silme yetkiniz yok.'})
        messages.error(request, 'Bu yorumu silme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project_id)
    deleted_by_admin = request.user != comment.author
    author_id = comment.author_id
    if deleted_by_admin:
        record_audit_event(
            actor=request.user,
            action='project.comment_deleted',
            target=comment,
            request=request,
            metadata={'comment_author_id': author_id, 'project_id': project_id},
        )
    comment.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, 'Yorumunuz başarıyla silindi.')
    return redirect('projects:project_detail', project_id=project_id)


@login_required
@require_POST
def approve_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    if request.user != project.advisor and not request.user.is_staff:
        messages.error(request, 'Bu projeyi onaylama yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if project.approval_status not in {'pending', 'revision_requested'}:
        messages.error(request, 'Bu proje onay aşamasında değil.')
        return redirect('projects:project_detail', project_id=project.id)
    
    project.status = 'approved'
    project.approval_status = 'approved'
    project.save(update_fields=['status', 'approval_status', 'updated_at'])
    create_notification(
        recipient=project.created_by,
        actor=request.user,
        notification_type='project_approved',
        message=f'“{project.title}” proje fikrin onaylandı.',
        target_url=project.get_absolute_url(),
    )
    messages.success(request, 'Proje fikri onaylandı.')
    
    return redirect('projects:project_detail', project_id=project.id)


@login_required
@require_POST
def send_feedback(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    if request.user != project.advisor and not request.user.is_staff:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Geri bildirim gönderme yetkiniz yok.'})
        messages.error(request, 'Geri bildirim gönderme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if project.approval_status != 'pending':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Bu proje değerlendirme aşamasında değil.'})
        messages.error(request, 'Bu proje değerlendirme aşamasında değil.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        try:
            feedback = project.feedback
            form = ProjectFeedbackForm(request.POST, instance=feedback)
        except ProjectFeedback.DoesNotExist:
            form = ProjectFeedbackForm(request.POST)
        
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.project = project
            feedback.teacher = request.user
            feedback.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            
            messages.success(request, 'Geri bildirim gönderildi.')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {}
                for field, field_errors in form.errors.items():
                    errors[field] = field_errors[0] if field_errors else 'Bu alan geçersiz.'
                return JsonResponse({'success': False, 'error': 'Form doğrulama hatası', 'errors': errors})
    
    return redirect('projects:project_detail', project_id=project.id)


@login_required
@require_POST
def start_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)

    # Prevent alumni from changing project status
    if hasattr(request.user, 'profile') and request.user.profile.user_type == 'alumni':
        messages.error(request, 'Mezunlar proje durumunu değiştiremez.')
        return redirect('projects:project_detail', project_id=project.id)

    is_team_member = request.user in project.team.all()
    if request.user != project.created_by and not is_team_member:
        messages.error(request, 'Bu projeyi başlatma yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)

    if project.approval_status != 'approved' or project.development_status not in {'idea', 'planning', 'on_hold'}:
        messages.error(request, 'Bu proje henüz fikir onay aşamasında değil.')
        return redirect('projects:project_detail', project_id=project.id)

    project.status = 'in_progress'
    project.development_status = 'in_progress'
    project.save(update_fields=['status', 'development_status', 'updated_at'])
    messages.success(request, 'Proje başlatıldı! Çalışmalara başlayabilirsiniz.')

    return redirect('projects:project_detail', project_id=project.id)


@login_required
@require_POST
def complete_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)

    # Prevent alumni from changing project status
    if hasattr(request.user, 'profile') and request.user.profile.user_type == 'alumni':
        messages.error(request, 'Mezunlar proje durumunu değiştiremez.')
        return redirect('projects:project_detail', project_id=project.id)

    is_team_member = request.user in project.team.all()
    is_advisor = request.user == project.advisor
    if request.user != project.created_by and not is_team_member and not is_advisor and not request.user.is_staff:
        messages.error(request, 'Bu projeyi tamamlama yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)

    if project.development_status != 'in_progress':
        messages.error(request, 'Bu proje devam ediyor durumunda değil.')
        return redirect('projects:project_detail', project_id=project.id)

    project.status = 'completed'
    project.development_status = 'completed'
    project.save(update_fields=['status', 'development_status', 'updated_at'])
    messages.success(request, 'Proje tamamlandı!')
    
    return redirect('projects:project_detail', project_id=project.id)


@login_required
def get_feedback(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    user = request.user
    is_team_member = project.team.filter(pk=user.pk).exists()
    is_advisor = user == project.advisor
    is_staff_or_teacher = _is_platform_staff(user)
    
    if not (is_team_member or is_advisor or is_staff_or_teacher):
        return JsonResponse({'success': False, 'error': 'Geri bildirimi görüntüleme yetkiniz yok.'})
    
    try:
        feedback = project.feedback
        return JsonResponse({
            'success': True,
            'content': feedback.content,
            'teacher_name': feedback.teacher.get_full_name(),
            'teacher_id': feedback.teacher.id,
            'created_at': feedback.created_at.strftime('%d.%m.%Y %H:%M'),
            'updated_at': feedback.updated_at.strftime('%d.%m.%Y %H:%M'),
        })
    except ProjectFeedback.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Henüz geri bildirim yok.'})
@login_required
@require_POST
def change_project_status(request, project_id):
    import json
    project = get_object_or_404(Project, id=project_id)

    user = request.user

    # Prevent alumni from changing project status
    if hasattr(user, 'profile') and user.profile.user_type == 'alumni':
        return JsonResponse({'success': False, 'error': 'Mezunlar proje durumunu değiştiremez.'})

    is_advisor = user == project.advisor
    if not (is_advisor or _is_platform_staff(user)):
        return JsonResponse({'success': False, 'error': 'Durum değiştirme yetkiniz yok.'})

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'success': False, 'error': 'Geçersiz istek verisi.'}, status=400)
    new_status = data.get('status')

    transitions = {
        'draft': ['in_review'],
        'in_review': ['approved'],
        'approved': ['in_progress'],
        'in_progress': ['completed'],
        'completed': ['in_progress'],
    }
    allowed = transitions.get(project.status, [])
    if new_status not in allowed:
        return JsonResponse({'success': False, 'error': f"'{project.get_status_display()}' durumundan geçiş yapılamaz."})

    project.status = new_status
    approval_map = {
        'draft': 'draft',
        'in_review': 'pending',
        'approved': 'approved',
        'in_progress': 'approved',
        'completed': 'approved',
    }
    development_map = {
        'draft': 'idea',
        'in_review': 'planning',
        'approved': 'planning',
        'in_progress': 'in_progress',
        'completed': 'completed',
    }
    project.approval_status = approval_map[new_status]
    project.development_status = development_map[new_status]
    project.save(update_fields=['status', 'approval_status', 'development_status', 'updated_at'])
    return JsonResponse({
        'success': True,
        'new_status': new_status,
        'new_status_display': project.get_status_display(),
    })
