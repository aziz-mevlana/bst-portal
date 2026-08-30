from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from projects.models import Project, ProjectRequest, ProjectCategory, ProjectSave, Technology
from accounts.models import CommunityRegistration, MODERATION_REASON_CHOICES, Profile
from accounts.models import UserModerationAction, UserReport, WebsiteModerationHistory
from accounts.policies import can_moderate_target, can_review_website
from accounts.policies import can_manage_events, can_manage_news
from accounts.role_services import ASSIGNABLE_STUDENT_ROLES, change_student_authority_role
from django.contrib.sessions.models import Session
from django.utils.dateparse import parse_datetime
from alumni.models import Alumni, AlumniRegistrationRequest
from alumni.services import (
    approve_existing_registration, approve_new_registration, reject_registration,
    unlink_alumni_account,
)
from core.notifications import create_notification
from django.contrib.auth.models import User
import json
import io
import logging
from core.audit import record_audit_event
from core.models import AnalyticsEvent, AuditLog
from django.utils import timezone
from datetime import timedelta


logger = logging.getLogger(__name__)


ANALYTICS_LABELS = {
    'profile_view': 'Profil Görüntülemeleri',
    'demo_click': 'Proje Bağlantısı Tıklamaları',
    'github_click': 'GitHub Bağlantısı Tıklamaları',
    'event_registration': 'Etkinlik Kayıtları',
    'mentorship_request': 'Mentorluk Talepleri',
    'search': 'Portal Aramaları',
    'ai_answer': 'AI Asistan Kullanımı',
    'company_contact': 'Şirket İletişim Talepleri',
}

ACTIVITY_LABELS = {
    'team.created': '{actor} yeni bir ekip oluşturdu.',
    'team.invited': '{actor} bir ekip daveti gönderdi.',
    'team.invite_accepted': '{actor} bir ekip davetini kabul etti.',
    'team.invite_rejected': '{actor} bir ekip davetini reddetti.',
    'team.disbanded': '{actor} bir ekibi dağıttı.',
    'project.featured': '{actor} bir projeyi öne çıkardı.',
    'project.unfeatured': '{actor} bir projenin öne çıkarma durumunu kaldırdı.',
    'project.created': '{actor} yeni bir proje oluşturdu.',
    'project.updated': '{actor} bir projeyi güncelledi.',
    'project.media_deleted': '{actor} bir proje görselini kaldırdı.',
    'project.cover_updated': '{actor} bir projenin kapak görselini değiştirdi.',
    'project_request.created': '{actor} yeni bir proje isteği oluşturdu.',
    'project_request.deleted': '{actor} bir proje ilanını sildi.',
    'project_request.application_accepted': '{actor} bir proje başvurusunu kabul etti.',
    'alumni.registration_approved': '{actor} bir mezun kayıt talebini onayladı.',
    'alumni.registration_rejected': '{actor} bir mezun kayıt talebini reddetti.',
    'profile.website_approved': '{actor} bir kişisel site bağlantısını onayladı.',
    'profile.website_rejected': '{actor} bir kişisel site bağlantısını reddetti.',
    'news.approved': '{actor} bir haberi onayladı.',
    'opportunity.created': '{actor} yeni bir kariyer ilanı oluşturdu.',
    'opportunity.approved': '{actor} bir kariyer ilanını onayladı.',
    'opportunity.deleted': '{actor} bir kariyer ilanını sildi.',
    'user.role_changed': '{actor} bir kullanıcı rolünü değiştirdi.',
    'collaboration.first_reviewed': '{actor} bir iş birliği talebinin ilk incelemesini tamamladı.',
    'collaboration.published': '{actor} bir iş birliği talebini yayımladı.',
    'contributor_application.approved': '{actor} bir katkıcı başvurusunu onayladı.',
    'contributor_application.rejected': '{actor} bir katkıcı başvurusunu reddetti.',
    'approved_member_application.approved': '{actor} bir Onaylı Üye başvurusunu onayladı.',
    'approved_member_application.rejected': '{actor} bir Onaylı Üye başvurusunu reddetti.',
}


def _can_review_contributor_applications(user):
    return bool(
        user.is_authenticated
        and (is_admin(user) or user.has_perm('accounts.review_contributor_applications'))
    )


def _recent_activity_feed(limit=6):
    rows = AuditLog.objects.filter(action__in=ACTIVITY_LABELS).select_related('actor')[:limit]
    activities = []
    for row in rows:
        actor = 'Sistem'
        if row.actor_id:
            actor = row.actor.get_full_name() or row.actor.username
        activities.append({
            'message': ACTIVITY_LABELS[row.action].format(actor=actor),
            'created_at': row.created_at,
        })
    return activities


def is_teacher_or_staff(user):
    """Check if user is teacher or staff student"""
    if not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return hasattr(user, 'profile') and user.profile.user_type in ['teacher', 'staff_student']


def is_student(user):
    """Students keep their personal workspace after becoming a BST authority."""
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type in {'student', 'staff_student'}


def is_alumni(user):
    """Check if user is an alumni"""
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type == 'alumni'


def is_admin(user):
    """Only Django staff/superusers can perform account administration."""
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


DASHBOARD_PAGE_SIZE = 12


def dashboard_home(request):
    """Main dashboard that routes to role-specific home page"""
    user = request.user

    if not user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    if not hasattr(user, 'profile'):
        return render(request, 'dashboard/access_denied.html')

    user_type = user.profile.user_type

    if user.is_staff or user.is_superuser or user_type == 'teacher':
        return teacher_dashboard_home(request)
    elif user_type in {'student', 'staff_student'}:
        return student_dashboard_home(request)
    elif user_type == 'alumni':
        return alumni_dashboard_home(request)
    elif user_type == 'approved_member':
        return community_dashboard_home(request)
    elif user_type == 'visitor':
        return redirect('portal:index')
    else:
        return render(request, 'dashboard/access_denied.html')


def community_dashboard_home(request):
    application = CommunityRegistration.objects.filter(user=request.user).first()
    saved_projects = ProjectSave.objects.filter(user=request.user).select_related(
        'project', 'project__project_type'
    )[:6]
    return render(request, 'dashboard/community_home.html', {
        'application': application,
        'saved_projects': saved_projects,
        'can_share_content': request.user.profile.user_type == 'approved_member',
    })


def student_dashboard_home(request):
    """Student dashboard home"""
    if not is_student(request.user):
        return render(request, 'dashboard/access_denied.html')

    user = request.user
    student_class = user.profile.class_level if hasattr(user.profile, 'class_level') else None

    my_projects = Project.objects.filter(
        Q(created_by=user) | Q(team=user)
    ).distinct().select_related(
        'advisor', 'project_request', 'project_type'
    ).prefetch_related('team', 'categories', 'technologies', 'media')

    available_requests = ProjectRequest.objects.filter(
        status='open', created_project__isnull=True,
    ).filter(
        Q(deadline__isnull=True) | Q(deadline__gte=timezone.localdate())
    ).select_related('teacher', 'teacher__profile', 'project_type')[:5]

    from accounts.portfolio_feedback import build_portfolio_feedback
    from events.models import EventRegistration

    portfolio_feedback = build_portfolio_feedback(user)
    upcoming_registrations = EventRegistration.objects.filter(
        user=user,
        status__in={'registered', 'waitlisted'},
        event__end_date__gte=timezone.now(),
        event__is_active=True,
    ).select_related('event').order_by('event__start_date')[:3]
    active_projects = my_projects.filter(development_status__in={'planning', 'in_progress'})
    completed_projects = my_projects.filter(development_status='completed')

    context = {
        'user_type': user.profile.user_type,
        'student_class': student_class,
        'my_projects': my_projects[:6],
        'project_count': my_projects.count(),
        'active_project_count': active_projects.count(),
        'completed_project_count': completed_projects.count(),
        'saved_project_count': user.saved_projects.count(),
        'team_count': user.team_memberships.count(),
        'pending_invitation_count': user.team_invitations.filter(status='pending').count(),
        'pending_application_count': user.project_request_applications.filter(status='pending').count(),
        'available_requests': available_requests,
        'available_request_count': ProjectRequest.objects.filter(
            status='open', created_project__isnull=True,
        ).filter(Q(deadline__isnull=True) | Q(deadline__gte=timezone.localdate())).count(),
        'upcoming_registrations': upcoming_registrations,
        'portfolio_score': portfolio_feedback['score'],
        'portfolio_next_steps': portfolio_feedback['items'][:3],
    }
    return render(request, 'dashboard/home_student.html', context)


def student_my_projects(request):
    """Student's own projects list"""
    if not is_student(request.user):
        return render(request, 'dashboard/access_denied.html')

    user = request.user
    my_projects = Project.objects.filter(
        Q(created_by=user) | Q(team=user)
    ).distinct().select_related('advisor', 'project_request').prefetch_related('team', 'categories', 'technologies')

    return render(request, 'dashboard/student_projects.html', {
        'projects': my_projects,
    })


def alumni_projects(request):
    """Redirect alumni to projects list"""
    from django.shortcuts import redirect
    if not is_alumni(request.user):
        return render(request, 'dashboard/access_denied.html')
    return redirect('dashboard:projects')


def alumni_dashboard_home(request):
    """Alumni dashboard home"""
    if not is_alumni(request.user):
        return render(request, 'dashboard/access_denied.html')

    user = request.user

    try:
        alumni = Alumni.objects.get(user=user)
    except Alumni.DoesNotExist:
        alumni = None

    context = {
        'user_type': 'alumni',
        'alumni': alumni,
    }
    return render(request, 'dashboard/home_alumni.html', context)


def dashboard_news(request):
    """Manage AI fetched news"""
    if not can_manage_news(request.user):
        raise PermissionDenied

    from news.models import Article, NewsKeyword

    pending_news = Article.objects.filter(is_approved=False).order_by('-date')
    approved_news = Article.objects.filter(is_approved=True).order_by('-date')
    keywords = NewsKeyword.objects.all()

    context = {
        'pending_news': pending_news,
        'approved_news': approved_news,
        'keywords': keywords,
    }
    return render(request, 'dashboard/news_list.html', context)


@login_required
def dashboard_events(request):
    """Event management inside the dashboard shell."""

    if not can_manage_events(request.user):
        raise PermissionDenied

    from events.models import Event

    now = timezone.now()
    query = request.GET.get('q', '').strip()[:120]
    event_type = request.GET.get('type', '')
    period = request.GET.get('period', 'upcoming')
    if period not in {'upcoming', 'past', 'all'}:
        period = 'upcoming'
    allowed_types = {value for value, _label in Event.EVENT_TYPE_CHOICES}
    if event_type not in allowed_types:
        event_type = ''

    events = Event.objects.select_related('created_by').annotate(
        active_registration_count=Count(
            'registrations',
            filter=Q(registrations__status__in={'registered', 'attended'}),
            distinct=True,
        ),
        waitlist_count=Count(
            'registrations',
            filter=Q(registrations__status='waitlisted'),
            distinct=True,
        ),
    )
    if query:
        events = events.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
        )
    if event_type:
        events = events.filter(event_type=event_type)
    if period == 'upcoming':
        events = events.filter(end_date__gte=now)
    elif period == 'past':
        events = events.filter(end_date__lt=now)

    context = {
        'events': events.order_by('start_date' if period == 'upcoming' else '-start_date')[:100],
        'query': query,
        'selected_type': event_type,
        'selected_period': period,
        'event_types': Event.EVENT_TYPE_CHOICES,
        'can_create_event': can_manage_events(request.user, 'add'),
        'event_stats': {
            'upcoming': Event.objects.filter(is_active=True, end_date__gte=now).count(),
            'registration_open': Event.objects.filter(
                is_active=True, allow_registration=True, start_date__gt=now,
            ).count(),
            'past': Event.objects.filter(end_date__lt=now).count(),
        },
    }
    return render(request, 'dashboard/events.html', context)


@login_required
def news_source_preview(request, news_id):
    if not can_manage_news(request.user):
        raise PermissionDenied
    from news.models import Article
    from news.source_reader import SourceReadError, read_source

    article = Article.objects.filter(pk=news_id).first()
    if article is None:
        return JsonResponse({'success': False, 'error': 'Haber bulunamadı.'}, status=404)
    source_url = article.source_url or article.url
    if not source_url:
        return JsonResponse({'success': False, 'error': 'Bu haber için kaynak adresi bulunmuyor.'}, status=400)
    try:
        preview = read_source(source_url)
    except SourceReadError as exc:
        return JsonResponse({
            'success': False,
            'error': str(exc),
            'source_url': source_url,
        }, status=422)
    return JsonResponse({
        'success': True,
        'title': preview['title'] or article.title,
        'source': article.source or preview['url'],
        'date': article.date.strftime('%d.%m.%Y %H:%M'),
        'content': preview['content'],
        'source_url': preview['url'],
    })


@login_required
@require_POST
def approve_news(request):
    """Approve a news article"""
    if not can_manage_news(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (TypeError, json.JSONDecodeError):
            return JsonResponse({'success': False, 'error': 'Geçersiz istek verisi.'}, status=400)
        news_id = data.get('news_id')

        from news.models import Article
        try:
            article = Article.objects.get(id=news_id)
            article.is_approved = True
            article.save()
            record_audit_event(actor=request.user, action='news.approved', target=article, request=request)
            return JsonResponse({'success': True})
        except Article.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Haber bulunamadı.'})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
@require_POST
def reject_news(request):
    """Reject/delete a news article"""
    if not can_manage_news(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (TypeError, json.JSONDecodeError):
            return JsonResponse({'success': False, 'error': 'Geçersiz istek verisi.'}, status=400)
        news_id = data.get('news_id')

        from news.models import Article
        try:
            article = Article.objects.get(id=news_id)
            record_audit_event(actor=request.user, action='news.deleted', target=article, request=request)
            article.delete()
            return JsonResponse({'success': True})
        except Article.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Haber bulunamadı.'})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
def delete_news(request):
    """Delete a news article"""
    return reject_news(request)


@login_required
@require_POST
def approve_all_news(request):
    """Approve all pending news"""
    if not can_manage_news(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    from news.models import Article
    count = Article.objects.filter(is_approved=False).update(is_approved=True)

    return JsonResponse({'success': True, 'count': count})


@login_required
@require_POST
def bulk_delete_news(request):
    if not can_manage_news(request.user):
        raise PermissionDenied
    try:
        if request.content_type == 'application/json':
            values = json.loads(request.body).get('ids', [])
        else:
            values = request.POST.getlist('article_ids')
        ids = sorted({int(value) for value in values if str(value).isdigit()})
    except (TypeError, ValueError, json.JSONDecodeError):
        ids = []
    if not ids:
        return JsonResponse({'success': False, 'error': 'Geçerli bir haber listesi seçilmedi.'}, status=400)
    from news.models import Article
    with transaction.atomic():
        articles = list(Article.objects.select_for_update().filter(pk__in=ids))
        for article in articles:
            record_audit_event(actor=request.user, action='news.deleted', target=article, request=request)
        article_count = len(articles)
        Article.objects.filter(pk__in=[item.pk for item in articles]).delete()
    return JsonResponse({'success': True, 'count': article_count})


@login_required
def news_keywords(request):
    """Add or update news keywords"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        keyword = data.get('keyword', '').strip()

        if not keyword:
            return JsonResponse({'success': False, 'error': 'Anahtar kelime gerekli.'})

        from news.models import NewsKeyword
        NewsKeyword.objects.get_or_create(keyword=keyword)
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
@require_POST
def delete_keyword(request):
    """Delete a news keyword"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        keyword_id = data.get('keyword_id')

        from news.models import NewsKeyword
        NewsKeyword.objects.get(id=keyword_id).delete()
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
@require_POST
def fetch_news_command(request):
    """Trigger news fetch command"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    output = io.StringIO()
    try:
        call_command('fetch_news', stdout=output, stderr=output)
        return JsonResponse({'success': True, 'output': output.getvalue()})
    except CommandError as exc:
        logger.warning('Haber çekme komutu başarısız: %s', exc)
        return JsonResponse({'success': False, 'output': 'Haberler çekilemedi.'}, status=400)
    except Exception:
        logger.exception('Haber çekme komutunda beklenmeyen hata.')
        return JsonResponse({'success': False, 'output': 'Beklenmeyen bir hata oluştu.'}, status=500)


def teacher_dashboard_home(request):
    """Teacher/Admin dashboard home"""
    if not is_teacher_or_staff(request.user):
        raise PermissionDenied

    user = request.user
    user_type = user.profile.user_type

    from .statistics import dashboard_statistics
    statistics = dashboard_statistics()

    analytics_rows = AnalyticsEvent.objects.filter(
        date_bucket__gte=timezone.localdate() - timedelta(days=30)
    ).values('event_type', 'succeeded').annotate(total=Count('id'))
    analytics_totals = {}
    for row in analytics_rows:
        analytics_totals.setdefault(row['event_type'], {'total': 0, 'successful': 0})
        analytics_totals[row['event_type']]['total'] += row['total']
        if row['succeeded'] is True:
            analytics_totals[row['event_type']]['successful'] += row['total']
    analytics_summary = [
        {
            'key': event_type,
            'label': ANALYTICS_LABELS.get(event_type, dict(AnalyticsEvent.EVENT_CHOICES).get(event_type, 'Diğer Etkinlik')),
            'total': values['total'],
            'successful': values['successful'],
            'show_success': event_type in {'search', 'ai_answer'},
        }
        for event_type, values in sorted(
            analytics_totals.items(), key=lambda item: (-item[1]['total'], item[0])
        )[:4]
    ]

    context = {
        'total_alumni': statistics['kpis']['alumni'],
        'total_projects': statistics['kpis']['projects'],
        'total_students': statistics['kpis']['students'],
        'pending_approvals': statistics['kpis']['pending_projects'],
        'user_type': user_type,
        'analytics_summary': analytics_summary,
        'recent_activities': _recent_activity_feed(),
        **statistics,
    }
    return render(request, 'dashboard/home_teacher.html', context)


def dashboard_skills(request):
    """Manage categories and technologies"""
    if not (is_admin(request.user) or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'):
        raise PermissionDenied
    
    if request.method == 'POST':
        data = request.POST
        item_type = data.get('type')
        item_id = data.get('id')
        name = data.get('name', '').strip()
        color = data.get('color', '#3B82F6')
        
        if item_type == 'category':
            if item_id:
                cat = ProjectCategory.objects.get(id=item_id)
                cat.name = name
                cat.color = color
                cat.save()
            else:
                ProjectCategory.objects.create(name=name, color=color)
        
        elif item_type == 'technology':
            if item_id:
                tech = Technology.objects.get(id=item_id)
                tech.name = name
                tech.color = color
                tech.save()
            else:
                Technology.objects.create(name=name, color=color)
        
        return JsonResponse({'success': True})
    
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    
    context = {
        'categories': categories,
        'technologies': technologies,
    }
    return render(request, 'dashboard/skills.html', context)


@login_required
@require_POST
def delete_skill(request):
    """Delete category or technology"""
    if not (is_admin(request.user) or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})
    
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        item_type = data.get('type')
        item_id = data.get('id')
        
        if item_type == 'category':
            ProjectCategory.objects.filter(id=item_id).update(is_active=False)
        elif item_type == 'technology':
            Technology.objects.filter(id=item_id).update(is_active=False)
        
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


def dashboard_requests(request):
    if not (
        is_admin(request.user)
        or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'
        or request.user.has_perm('accounts.review_project_requests')
    ):
        raise PermissionDenied
    
    user = request.user
    
    # Filtreleme
    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    
    requests = (
        ProjectRequest.objects.select_related('project_type', 'teacher')
        .prefetch_related('projects')
        .annotate(application_count=Count('applications', distinct=True))
    )
    can_review_all = is_admin(user) or user.has_perm('accounts.review_project_requests')
    if not can_review_all:
        requests = requests.filter(teacher=user)
    
    if query:
        requests = requests.filter(title__icontains=query)
    
    if status_filter:
        requests = requests.filter(status=status_filter)
    
    context = {
        'requests': requests,
        'query': query,
        'status_filter': status_filter,
        'status_choices': ProjectRequest.REQUEST_STATUS_CHOICES,
        'can_create_request': is_admin(user) or user.profile.user_type == 'teacher',
    }
    return render(request, 'dashboard/requests.html', context)


def dashboard_students(request):
    if not (
        is_admin(request.user)
        or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'
        or request.user.has_perm('accounts.moderate_accounts')
    ):
        raise PermissionDenied
    
    query = request.GET.get('q', '')
    class_level = request.GET.get('class_level', '')
    
    # BST yetkilileri de öğrencidir; Django yönetici hesaplarını dahil etme.
    students = User.objects.filter(
        profile__user_type__in=['student', 'staff_student'],
        is_staff=False,
        is_superuser=False,
    ).select_related('profile').order_by('pk')
    
    if query:
        students = students.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(username__icontains=query)
        )
    
    if class_level:
        students = students.filter(
            Q(profile__class_level=class_level)
        )
    
    total_count = students.count()
    page_size = DASHBOARD_PAGE_SIZE
    students_page = students[:page_size]
    has_more = total_count > page_size
    
    context = {
        'students': students_page,
        'query': query,
        'class_level': class_level,
        'class_choices': Profile.CLASS_CHOICES,
        'has_more': has_more,
        'next_offset': page_size,
        'total_count': total_count,
    }
    return render(request, 'dashboard/students.html', context)


def dashboard_students_load_more(request):
    if not (
        is_admin(request.user)
        or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'
        or request.user.has_perm('accounts.moderate_accounts')
    ):
        raise PermissionDenied

    offset = int(request.GET.get('offset', 0))
    query = request.GET.get('q', '')
    class_level = request.GET.get('class_level', '')
    
    students = User.objects.filter(
        profile__user_type__in=['student', 'staff_student'],
        is_staff=False,
        is_superuser=False,
    ).select_related('profile').order_by('pk')
    
    if query:
        students = students.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(username__icontains=query)
        )
    
    if class_level:
        students = students.filter(
            Q(profile__class_level=class_level)
        )
    
    total_count = students.count()
    students_page = students[offset:offset + DASHBOARD_PAGE_SIZE]
    has_more = offset + DASHBOARD_PAGE_SIZE < total_count
    
    html = render_to_string('dashboard/partials/student_row.html', {'students': students_page})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + DASHBOARD_PAGE_SIZE,
    })


@login_required
def dashboard_projects(request):
    user = request.user
    manager_access = is_admin(user)

    # User type for template
    user_type = user.profile.user_type if user and hasattr(user, 'profile') else None

    # Get filter parameters
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    request_id = request.GET.get('project_request', '')
    
    if manager_access:
        projects = Project.objects.all().prefetch_related('team', 'categories', 'technologies', 'project_request', 'advisor', 'created_by')
    else:
        projects = Project.objects.filter(
            Q(visibility__in={'public', 'unlisted'}, approval_status='approved')
            | Q(created_by=user)
            | Q(team=user)
            | Q(advisor=user)
            | Q(project_request__teacher=user)
        ).distinct().prefetch_related('team', 'categories', 'technologies', 'project_request')
    
    # Apply filters
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    
    if status:
        projects = projects.filter(status=status)
    
    if request_id:
        projects = projects.filter(project_request_id=request_id)
    
    total_count = projects.count()
    projects = projects[:DASHBOARD_PAGE_SIZE]
    has_more = total_count > DASHBOARD_PAGE_SIZE
    
    # Get teacher requests for the filter dropdown (only for teachers)
    if is_admin(user):
        teacher_requests = ProjectRequest.objects.all()
    elif getattr(user.profile, 'user_type', '') == 'teacher':
        teacher_requests = ProjectRequest.objects.filter(teacher=user)
    else:
        teacher_requests = ProjectRequest.objects.none()
    
    context = {
        'projects': projects,
        'query': query,
        'selected_status': status,
        'statuses': Project.STATUS_CHOICES,
        'teacher_requests': teacher_requests,
        'selected_request': request_id,
        'is_teacher_or_staff': manager_access,
        'user_type': user_type,
        'has_more': has_more,
        'next_offset': DASHBOARD_PAGE_SIZE,
    }
    return render(request, 'dashboard/projects.html', context)


@login_required
def dashboard_projects_load_more(request):
    user = request.user
    manager_access = is_admin(user)
    
    offset = int(request.GET.get('offset', 0))
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    request_id = request.GET.get('project_request', '')
    
    if manager_access:
        projects = Project.objects.all().prefetch_related('team', 'categories', 'technologies', 'project_request', 'advisor', 'created_by')
    else:
        projects = Project.objects.filter(
            Q(visibility__in={'public', 'unlisted'}, approval_status='approved')
            | Q(created_by=user)
            | Q(team=user)
            | Q(advisor=user)
            | Q(project_request__teacher=user)
        ).distinct().prefetch_related('team', 'categories', 'technologies', 'project_request')

    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if status:
        projects = projects.filter(status=status)
    if request_id:
        projects = projects.filter(project_request_id=request_id)

    total_count = projects.count()
    projects = projects[offset:offset + DASHBOARD_PAGE_SIZE]
    has_more = offset + DASHBOARD_PAGE_SIZE < total_count
    
    html = render_to_string('dashboard/partials/project_card.html', {'projects': projects})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + DASHBOARD_PAGE_SIZE,
    })


def dashboard_alumni(request):
    if not (
        is_admin(request.user)
        or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'
        or request.user.has_perm('accounts.moderate_accounts')
    ):
        raise PermissionDenied

    query = request.GET.get('q', '')
    experience = request.GET.get('experience', '')
    mentoring = request.GET.get('mentoring', '')
    matched = request.GET.get('matched', '')
    category = request.GET.get('category', '')
    technology = request.GET.get('technology', '')

    alumni = Alumni.objects.select_related('user', 'user__profile').prefetch_related('technologies', 'categories')

    if query:
        alumni = alumni.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(full_name__icontains=query) |
            Q(company__icontains=query) |
            Q(current_position__icontains=query)
        )

    if experience:
        alumni = alumni.filter(experience_level=experience)

    if mentoring == '1':
        alumni = alumni.filter(is_available_for_mentoring=True)

    if matched == 'yes':
        alumni = alumni.filter(user__isnull=False)
    elif matched == 'no':
        alumni = alumni.filter(user__isnull=True)

    if category:
        alumni = alumni.filter(categories__id=category)

    if technology:
        alumni = alumni.filter(technologies__id=technology)

    total_count = alumni.count()
    alumni_list = alumni[:DASHBOARD_PAGE_SIZE]
    has_more = total_count > DASHBOARD_PAGE_SIZE
    next_offset = DASHBOARD_PAGE_SIZE if has_more else 0

    context = {
        'alumni_list': alumni_list,
        'total_count': total_count,
        'has_more': has_more,
        'next_offset': next_offset,
        'query': query,
        'selected_experience': experience,
        'selected_mentoring': mentoring,
        'selected_matched': matched,
        'selected_category': category,
        'selected_technology': technology,
        'experience_choices': Alumni.EXPERIENCE_LEVEL_CHOICES,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
        'can_match_accounts': is_admin(request.user),
    }
    return render(request, 'dashboard/alumni.html', context)


def dashboard_alumni_load_more(request):
    if not (
        is_admin(request.user)
        or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'
        or request.user.has_perm('accounts.moderate_accounts')
    ):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    offset = int(request.GET.get('offset', 0))
    query = request.GET.get('q', '')
    experience = request.GET.get('experience', '')
    mentoring = request.GET.get('mentoring', '')
    matched = request.GET.get('matched', '')
    category = request.GET.get('category', '')
    technology = request.GET.get('technology', '')

    alumni = Alumni.objects.select_related('user', 'user__profile').prefetch_related('technologies', 'categories')

    if query:
        alumni = alumni.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(full_name__icontains=query) |
            Q(company__icontains=query) |
            Q(current_position__icontains=query)
        )

    if experience:
        alumni = alumni.filter(experience_level=experience)

    if mentoring == '1':
        alumni = alumni.filter(is_available_for_mentoring=True)

    if matched == 'yes':
        alumni = alumni.filter(user__isnull=False)
    elif matched == 'no':
        alumni = alumni.filter(user__isnull=True)

    if category:
        alumni = alumni.filter(categories__id=category)

    if technology:
        alumni = alumni.filter(technologies__id=technology)

    total_count = alumni.count()
    alumni_page = alumni[offset:offset + DASHBOARD_PAGE_SIZE]
    has_more = offset + DASHBOARD_PAGE_SIZE < total_count

    html = render_to_string('dashboard/partials/alumni_row.html', {'alumni_list': alumni_page})

    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + DASHBOARD_PAGE_SIZE,
    })


@login_required
@require_POST
def match_alumni(request):
    """Mezun kaydını bir kullanıcı profiliyle eşleştir"""
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        alumni_id = data.get('alumni_id')
        user_id = data.get('user_id')

        try:
            alumni = Alumni.objects.get(id=alumni_id)
        except Alumni.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Mezun kaydı bulunamadı.'})

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Kullanıcı bulunamadı.'})

        # Bu kullanıcı zaten bir mezun kaydına bağlı mı kontrol et
        if Alumni.objects.filter(user=user).exclude(id=alumni_id).exists():
            return JsonResponse({'success': False, 'error': 'Bu kullanıcı zaten başka bir mezun kaydına bağlı.'})

        alumni.user = user
        alumni.save()
        record_audit_event(
            actor=request.user,
            action='alumni.account_matched',
            target=alumni,
            metadata={'user_id': user.pk},
            request=request,
        )

        return JsonResponse({
            'success': True,
            'user_name': user.get_full_name(),
            'user_email': user.email,
        })

    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})


@login_required
@require_POST
def unmatch_alumni(request):
    """Mezun kaydından kullanıcı bağlantısını kaldır"""
    import json
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        alumni_id = data.get('alumni_id')

        try:
            alumni = Alumni.objects.get(id=alumni_id)
        except Alumni.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Mezun kaydı bulunamadı.'})

        description = str(data.get('description', '')).strip()
        try:
            unlink_alumni_account(
                alumni_id=alumni.pk, reviewer=request.user, description=description, request=request
            )
        except ValidationError as exc:
            return JsonResponse({'success': False, 'error': '; '.join(exc.messages)}, status=400)

        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})


@login_required
def alumni_registrations(request):
    if not (is_admin(request.user) or request.user.has_perm('accounts.review_alumni_registrations')):
        raise PermissionDenied
    status = request.GET.get('status', 'pending')
    registrations = AlumniRegistrationRequest.objects.select_related('user', 'reviewed_by', 'matched_alumni')
    if status:
        registrations = registrations.filter(status=status)
    return render(request, 'dashboard/alumni_registrations.html', {
        'registrations': registrations, 'selected_status': status,
        'statuses': AlumniRegistrationRequest.STATUS_CHOICES,
    })


@login_required
def alumni_registration_detail(request, registration_id):
    if not (is_admin(request.user) or request.user.has_perm('accounts.review_alumni_registrations')):
        raise PermissionDenied
    registration = get_object_or_404(
        AlumniRegistrationRequest.objects.select_related('user', 'reviewed_by', 'matched_alumni'),
        pk=registration_id,
    )
    query = request.GET.get('q', '').strip()
    candidates = Alumni.objects.filter(user__isnull=True)
    if query:
        candidates = candidates.filter(
            Q(full_name__icontains=query) | Q(student_number__icontains=query) |
            Q(graduation_year__icontains=query)
        )
    else:
        name_parts = [part for part in registration.full_name.split() if len(part) > 1]
        match_query = Q(graduation_year=registration.graduation_year)
        for part in name_parts[:2]:
            match_query |= Q(full_name__icontains=part)
        candidates = candidates.filter(match_query)
    return render(request, 'dashboard/alumni_registration_detail.html', {
        'registration': registration, 'candidates': candidates[:50], 'query': query,
        'reason_choices': MODERATION_REASON_CHOICES,
    })


def _registration_redirect(registration_id):
    return redirect('dashboard:alumni_registration_detail', registration_id=registration_id)


@login_required
@require_POST
def alumni_registration_link(request, registration_id):
    try:
        approve_existing_registration(
            registration_id=registration_id, alumni_id=request.POST.get('alumni_id'),
            reviewer=request.user, request=request,
        )
        messages.success(request, 'Mezun hesabı mevcut kayda bağlandı ve etkinleştirildi.')
    except (ValidationError, Alumni.DoesNotExist, AlumniRegistrationRequest.DoesNotExist) as exc:
        messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
    return _registration_redirect(registration_id)


@login_required
@require_POST
def alumni_registration_create(request, registration_id):
    try:
        approve_new_registration(
            registration_id=registration_id, reviewer=request.user,
            confirmed=request.POST.get('confirm_new') == 'yes', request=request,
        )
        messages.success(request, 'Yeni mezun kaydı oluşturuldu ve hesap etkinleştirildi.')
    except (ValidationError, IntegrityError, AlumniRegistrationRequest.DoesNotExist) as exc:
        messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
    return _registration_redirect(registration_id)


@login_required
@require_POST
def alumni_registration_reject(request, registration_id):
    try:
        reject_registration(
            registration_id=registration_id, reviewer=request.user,
            reason=request.POST.get('reason', ''), description=request.POST.get('description', ''),
            request=request,
        )
        messages.success(request, 'Mezun kayıt talebi reddedildi.')
    except (ValidationError, AlumniRegistrationRequest.DoesNotExist) as exc:
        messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
    return _registration_redirect(registration_id)


@login_required
def website_moderation(request):
    if not can_review_website(request.user):
        raise PermissionDenied
    profiles = Profile.objects.filter(website_status='pending').exclude(website_url='').select_related('user')
    return render(request, 'dashboard/website_moderation.html', {'profiles': profiles})


@login_required
@require_POST
@transaction.atomic
def website_review(request, profile_id):
    if not can_review_website(request.user):
        raise PermissionDenied
    profile = get_object_or_404(Profile.objects.select_for_update().select_related('user'), pk=profile_id)
    decision = request.POST.get('decision')
    reason = request.POST.get('reason', '').strip()
    description = request.POST.get('description', '').strip()
    if profile.website_status != 'pending' or decision not in {'approve', 'reject'}:
        messages.error(request, 'Başvuru artık beklemede değil veya işlem geçersiz.')
        return redirect('dashboard:website_moderation')
    if decision == 'reject' and (reason not in {v for v, _ in MODERATION_REASON_CHOICES} or not description):
        messages.error(request, 'Site reddi için standart neden ve açıklama zorunludur.')
        return redirect('dashboard:website_moderation')
    profile.website_status = 'approved' if decision == 'approve' else 'rejected'
    profile.website_reviewed_by = request.user
    profile.website_reviewed_at = timezone.now()
    profile.website_rejection_reason = reason if decision == 'reject' else ''
    profile.website_moderation_description = description
    profile.save(update_fields=[
        'website_status', 'website_reviewed_by', 'website_reviewed_at',
        'website_rejection_reason', 'website_moderation_description',
    ])
    history = WebsiteModerationHistory.objects.create(
        profile=profile, website_url=profile.website_url, status=profile.website_status,
        reason=reason if decision == 'reject' else '', description=description,
        performed_by=request.user,
    )
    create_notification(
        recipient=profile.user, actor=request.user, notification_type='website_review',
        title='Kişisel web sitesi incelemesi',
        message='Kişisel web siteniz onaylandı.' if decision == 'approve' else f'Kişisel web siteniz reddedildi: {description}',
        target_url=reverse('accounts:portfolio_settings'),
        dedupe_key=f'website-review:{history.pk}', force=True,
    )
    record_audit_event(
        actor=request.user, action=f'profile.website_{profile.website_status}', target=profile,
        request=request, metadata={'reason': reason, 'description': description, 'history_id': history.pk},
    )
    messages.success(request, 'Web sitesi inceleme kararı kaydedildi.')
    return redirect('dashboard:website_moderation')


@login_required
def search_users(request):
    """Eşleştirme için kullanıcı arama"""
    if not is_admin(request.user):
        return JsonResponse({'results': []})

    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'results': []})

    users = User.objects.filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(email__icontains=query)
    ).select_related('profile')[:20]

    results = []
    for user in users:
        user_type = ''
        if hasattr(user, 'profile'):
            user_type = user.profile.get_user_type_display()
        
        already_matched = Alumni.objects.filter(user=user).exists()
        
        results.append({
            'id': user.id,
            'name': user.get_full_name() or user.username,
            'email': user.email,
            'user_type': user_type,
            'already_matched': already_matched,
        })

    return JsonResponse({'results': results})


@login_required
def update_student_class(request):
    """Öğrenci sınıfını güncelle"""
    import json
    if not (is_admin(request.user) or getattr(getattr(request.user, 'profile', None), 'user_type', '') == 'teacher'):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        student_id = data.get('student_id')
        class_level = data.get('class_level')

        try:
            user = User.objects.get(id=student_id)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Kullanıcı bulunamadı.'})

        if not hasattr(user, 'profile'):
            return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})

        user.profile.class_level = class_level
        user.profile.save()

        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})


@login_required
def dashboard_academics(request):
    """List all academics (teachers)"""
    if not is_admin(request.user):
        raise PermissionDenied
    
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    
    # Get all teachers with their profiles
    academics = User.objects.filter(
        profile__user_type='teacher'
    ).select_related('profile')
    
    if query:
        academics = academics.filter(
            models.Q(first_name__icontains=query) |
            models.Q(last_name__icontains=query) |
            models.Q(email__icontains=query)
        )
    
    if status == 'pending':
        academics = academics.filter(is_active=False)
    elif status == 'active':
        academics = academics.filter(is_active=True)
    
    academics = academics.order_by('-date_joined')
    
    pending_count = academics.filter(is_active=False).count()
    active_count = academics.filter(is_active=True).count()
    
    return render(request, 'dashboard/academics.html', {
        'academics': academics,
        'pending_count': pending_count,
        'active_count': active_count,
        'total_count': academics.count(),
        'query': query,
        'selected_status': status,
    })


@login_required
@require_POST
def approve_academic(request):
    """Approve a pending academic"""
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})
    
    if request.method == 'POST':
        data = json.loads(request.body)
        user_id = data.get('user_id')
        
        try:
            user = User.objects.get(id=user_id, profile__user_type='teacher')
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Akademisyen bulunamadı.'})
        
        user.is_active = True
        user.save()
        user.profile.account_status = 'active'
        user.profile.academic_approved_at = timezone.now()
        user.profile.academic_approved_by = request.user
        user.profile.save(update_fields=['account_status', 'academic_approved_at', 'academic_approved_by'])
        UserModerationAction.objects.create(
            user=user, action_type='approve_academic', reason='other',
            description='Akademisyen kaydı yönetici tarafından onaylandı.', performed_by=request.user,
        )
        record_audit_event(actor=request.user, action='academic.approved', target=user, request=request)
        
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})


@login_required
@require_POST
def reject_academic(request):
    if not is_admin(request.user):
        raise PermissionDenied
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz istek.'}, status=400)
    reason = str(data.get('reason', '')).strip()
    if not reason:
        return JsonResponse({'success': False, 'error': 'Red nedeni zorunludur.'}, status=400)
    user = User.objects.filter(pk=data.get('user_id'), profile__user_type='teacher').select_related('profile').first()
    if not user:
        return JsonResponse({'success': False, 'error': 'Akademisyen bulunamadı.'}, status=404)
    user.is_active = False
    user.save(update_fields=['is_active'])
    user.profile.account_status = 'closed'
    user.profile.suspension_reason = reason
    user.profile.save(update_fields=['account_status', 'suspension_reason'])
    action = UserModerationAction.objects.create(
        user=user, action_type='reject_academic', reason='other', description=reason,
        performed_by=request.user,
    )
    record_audit_event(actor=request.user, action='academic.rejected', target=user, request=request, metadata={'moderation_action_id': action.pk})
    return JsonResponse({'success': True})


@login_required
def moderation_users(request):
    if not (is_admin(request.user) or request.user.has_perm('accounts.moderate_accounts')):
        raise PermissionDenied
    users = User.objects.select_related('profile').order_by('-date_joined')
    query = request.GET.get('q', '').strip()
    role = request.GET.get('role', '')
    status = request.GET.get('status', '')
    verified = request.GET.get('verified', '')
    if query:
        users = users.filter(
            Q(username__icontains=query) | Q(first_name__icontains=query) |
            Q(last_name__icontains=query) | Q(email__icontains=query) |
            Q(profile__student_number__icontains=query)
        )
    if role:
        users = users.filter(profile__user_type=role)
    if status:
        users = users.filter(profile__account_status=status)
    if verified == 'yes':
        users = users.filter(profile__institutional_email_verified_at__isnull=False)
    elif verified == 'no':
        users = users.filter(profile__institutional_email_verified_at__isnull=True)
    return render(request, 'dashboard/moderation_users.html', {
        'users': users[:200], 'query': query, 'selected_role': role,
        'selected_status': status, 'selected_verified': verified,
        'roles': Profile.USER_TYPE_CHOICES, 'statuses': Profile.ACCOUNT_STATUS_CHOICES,
    })


@login_required
def contributor_applications(request):
    if not _can_review_contributor_applications(request.user):
        raise PermissionDenied
    selected_status = request.GET.get('status', 'pending')
    valid_statuses = {'pending', 'approved', 'rejected'}
    if selected_status not in valid_statuses:
        selected_status = 'pending'
    applications = CommunityRegistration.objects.filter(
        wants_to_share=True, status=selected_status,
    ).select_related('user', 'user__profile', 'reviewed_by')
    counts = {
        row['status']: row['count']
        for row in CommunityRegistration.objects.filter(wants_to_share=True)
        .values('status').annotate(count=Count('pk'))
    }
    return render(request, 'dashboard/contributor_applications.html', {
        'applications': applications,
        'selected_status': selected_status,
        'pending_count': counts.get('pending', 0),
        'approved_count': counts.get('approved', 0),
        'rejected_count': counts.get('rejected', 0),
    })


@login_required
@require_POST
def contributor_application_review(request, application_id):
    if not _can_review_contributor_applications(request.user):
        raise PermissionDenied
    action = request.POST.get('action', '')
    reviewer_note = request.POST.get('reviewer_note', '').strip()
    if action not in {'approve', 'reject'}:
        messages.error(request, 'Geçersiz başvuru işlemi.')
        return redirect('dashboard:approved_member_applications')
    if action == 'reject' and not reviewer_note:
        messages.error(request, 'Reddedilen başvurular için açıklama zorunludur.')
        return redirect('dashboard:approved_member_applications')
    if len(reviewer_note) > 1000:
        messages.error(request, 'İnceleme notu en fazla 1000 karakter olabilir.')
        return redirect('dashboard:approved_member_applications')

    with transaction.atomic():
        application = get_object_or_404(
            CommunityRegistration.objects.select_for_update().select_related('user', 'user__profile'),
            pk=application_id, wants_to_share=True,
        )
        if application.status != 'pending':
            messages.info(request, 'Bu katkıcı başvurusu daha önce sonuçlandırılmış.')
            return redirect('dashboard:approved_member_applications')
        if application.user.profile.user_type != 'visitor':
            messages.error(request, 'Kullanıcının mevcut rolü bu başvuruyu sonuçlandırmaya uygun değil.')
            return redirect('dashboard:approved_member_applications')

        approved = action == 'approve'
        application.status = 'approved' if approved else 'rejected'
        application.reviewer_note = reviewer_note
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'reviewer_note', 'reviewed_by', 'reviewed_at', 'updated_at'])

        application.user.profile.user_type = 'approved_member' if approved else 'visitor'
        application.user.profile.save(update_fields=['user_type', 'updated_at'])
        record_audit_event(
            actor=request.user,
            action=f'approved_member_application.{application.status}',
            target=application.user,
            request=request,
            metadata={'application_id': application.pk, 'reviewer_note': reviewer_note},
        )
        create_notification(
            recipient=application.user,
            actor=request.user,
            notification_type='moderation',
            title='Onaylı Üye başvurunuz sonuçlandı',
            message=(
                'Onaylı Üye başvurunuz onaylandı. Artık BST Portal’da içerik paylaşabilirsiniz.'
                if approved else f'Onaylı Üye başvurunuz şu nedenle onaylanmadı: {reviewer_note}'
            ),
            target_url='/accounts/profile/',
            dedupe_key=f'approved-member-review:{application.pk}:{application.updated_at.timestamp()}',
            force=True,
        )

    messages.success(request, 'Onaylı Üye yetkisi verildi.' if approved else 'Başvuru reddedildi; kullanıcı Ziyaretçi olarak kaldı.')
    return redirect('dashboard:approved_member_applications')


@login_required
def moderation_user_detail(request, user_id):
    if not (is_admin(request.user) or request.user.has_perm('accounts.moderate_accounts')):
        raise PermissionDenied
    target = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
    can_change_role = bool(
        is_admin(request.user)
        and request.user.pk != target.pk
        and not target.is_staff
        and not target.is_superuser
        and target.profile.user_type in ASSIGNABLE_STUDENT_ROLES
    )
    return render(request, 'dashboard/moderation_user_detail.html', {
        'target_user': target,
        'history': target.moderation_actions.select_related('performed_by')[:50],
        'role_history': AuditLog.objects.filter(
            action='user.role_changed', target_type='auth.user', target_id=str(target.pk)
        ).select_related('actor')[:20],
        'reports': target.received_user_reports.select_related('reporter', 'reviewed_by')[:50],
        'reason_choices': MODERATION_REASON_CHOICES,
        'can_close_account': is_admin(request.user),
        'can_end_sessions': is_admin(request.user) or request.user.has_perm('accounts.end_user_sessions'),
        'can_change_role': can_change_role,
        'assignable_roles': ASSIGNABLE_STUDENT_ROLES.items(),
    })


@login_required
@require_POST
def change_user_role(request, user_id):
    if not is_admin(request.user):
        raise PermissionDenied
    target = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
    if request.POST.get('confirm_role_change') != 'yes':
        messages.error(request, 'Rol değişikliğini onaylamanız gerekiyor.')
        return redirect('dashboard:moderation_user_detail', user_id=target.pk)
    try:
        updated = change_student_authority_role(
            actor=request.user,
            target=target,
            new_role=request.POST.get('new_role', ''),
            description=request.POST.get('description', ''),
            request=request,
        )
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    else:
        messages.success(
            request,
            f'{updated.get_full_name() or updated.username} artık '
            f'{updated.profile.get_user_type_display()} rolünde.',
        )
    return redirect('dashboard:moderation_user_detail', user_id=target.pk)


@login_required
@require_POST
def moderate_user(request, user_id):
    if not (is_admin(request.user) or request.user.has_perm('accounts.moderate_accounts')):
        raise PermissionDenied
    target = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
    action = request.POST.get('action', '')
    reason = request.POST.get('reason', '').strip()
    description = request.POST.get('description', '').strip()
    allowed = {'suspend', 'reactivate', 'close', 'request_reverification', 'remove_photo', 'end_sessions'}
    if action not in allowed:
        messages.error(request, 'Geçersiz moderasyon işlemi.')
        return redirect('dashboard:moderation_user_detail', user_id=target.pk)
    if not can_moderate_target(request.user, target, action):
        raise PermissionDenied('Bu kullanıcı veya işlem için moderasyon yetkiniz yok.')
    valid_reasons = {value for value, _ in MODERATION_REASON_CHOICES}
    if reason not in valid_reasons or not description:
        messages.error(request, 'Standart neden ve ayrıntılı açıklama zorunludur.')
        return redirect('dashboard:moderation_user_detail', user_id=target.pk)

    expires_at = None
    profile = target.profile
    if action == 'suspend':
        raw_expires = request.POST.get('expires_at', '').strip()
        parsed = parse_datetime(raw_expires) if raw_expires else None
        if not parsed:
            messages.error(request, 'Askıya alma bitiş zamanı zorunludur.')
            return redirect('dashboard:moderation_user_detail', user_id=target.pk)
        expires_at = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        if expires_at <= timezone.now():
            messages.error(request, 'Bitiş zamanı gelecekte olmalıdır.')
            return redirect('dashboard:moderation_user_detail', user_id=target.pk)
        profile.account_status = 'suspended'
        profile.suspension_reason = description
        profile.suspended_until = expires_at
        profile.save(update_fields=['account_status', 'suspension_reason', 'suspended_until'])
        target.is_active = False
        target.save(update_fields=['is_active'])
    elif action == 'reactivate':
        profile.account_status = 'active'
        profile.suspension_reason = ''
        profile.suspended_until = None
        profile.save(update_fields=['account_status', 'suspension_reason', 'suspended_until'])
        target.is_active = True
        target.save(update_fields=['is_active'])
    elif action == 'close':
        profile.account_status = 'closed'
        profile.suspension_reason = description
        profile.suspended_until = None
        profile.save(update_fields=['account_status', 'suspension_reason', 'suspended_until'])
        target.is_active = False
        target.save(update_fields=['is_active'])
    elif action == 'request_reverification':
        profile.account_status = 'pending_email'
        profile.institutional_email_verified_at = None
        profile.save(update_fields=['account_status', 'institutional_email_verified_at'])
    elif action == 'remove_photo':
        profile.profile_picture = ''
        profile.save(update_fields=['profile_picture'])
    elif action == 'end_sessions':
        for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
            if session.get_decoded().get('_auth_user_id') == str(target.pk):
                session.delete()

    moderation = UserModerationAction.objects.create(
        user=target, action_type=action, reason=reason, description=description, performed_by=request.user,
        expires_at=expires_at,
    )
    record_audit_event(
        actor=request.user, action=f'user.{action}', target=target, request=request,
        metadata={'moderation_action_id': moderation.pk, 'reason': reason, 'description': description,
                  'expires_at': expires_at.isoformat() if expires_at else ''},
    )
    create_notification(
        recipient=target,
        actor=request.user,
        notification_type='moderation',
        title='Hesabınızla ilgili işlem',
        message=description,
        target_url='/accounts/portfolio/settings/',
        dedupe_key=f'user-moderation:{moderation.pk}',
        force=True,
    )
    messages.success(request, 'Moderasyon işlemi kaydedildi ve audit log oluşturuldu.')
    return redirect('dashboard:moderation_user_detail', user_id=target.pk)
