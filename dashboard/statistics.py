from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import Profile, UserReport
from alumni.models import Alumni, AlumniRegistrationRequest
from career.models import CollaborationRequest, MentorshipRequest, Opportunity
from events.models import Event
from news.models import Article
from projects.models import Project, ProjectAchievement, ProjectCategory, ProjectRequest, Team, Technology


def _distribution(queryset, field, choices):
    counts = dict(queryset.values_list(field).annotate(total=Count('pk')).values_list(field, 'total'))
    maximum = max(counts.values(), default=0)
    return [
        {'key': value, 'label': label, 'count': counts.get(value, 0),
         'percent': round((counts.get(value, 0) / maximum) * 100) if maximum else 0}
        for value, label in choices
    ]


def dashboard_statistics():
    now = timezone.now()
    active_users = User.objects.filter(is_active=True, profile__account_status='active')
    non_admin_profiles = Profile.objects.filter(user__is_staff=False, user__is_superuser=False)
    profile_roles = dict(
        non_admin_profiles.values_list('user_type').annotate(total=Count('pk')).values_list('user_type', 'total')
    )
    pending_reports = UserReport.objects.filter(status__in=['open', 'reviewing']).count()
    pending_websites = Profile.objects.filter(website_status='pending').exclude(website_url='').count()
    pending_alumni = AlumniRegistrationRequest.objects.filter(status='pending').count()
    pending_collaborations = CollaborationRequest.objects.filter(status='pending_review').count()
    pending_news = Article.objects.filter(is_approved=False).count()
    projects = Project.objects.all()
    class_profiles = non_admin_profiles.filter(user_type__in=['student', 'staff_student'])

    technology_rows = list(
        Technology.objects.annotate(total=Count('projects', distinct=True)).filter(total__gt=0).order_by('-total', 'name')[:6]
        .values('name', 'total')
    )
    category_rows = list(
        ProjectCategory.objects.annotate(total=Count('projects', distinct=True)).filter(total__gt=0).order_by('-total', 'name')[:6]
        .values('name', 'total')
    )
    for rows in (technology_rows, category_rows):
        maximum = max((row['total'] for row in rows), default=0)
        for row in rows:
            row['percent'] = round(row['total'] / maximum * 100) if maximum else 0

    active_projects = projects.filter(development_status__in=['planning', 'in_progress']).count()
    completed_projects = projects.filter(development_status='completed').count()
    ratio_total = active_projects + completed_projects
    return {
        'kpis': {
            'active_users': active_users.count(),
            'students': profile_roles.get('student', 0) + profile_roles.get('staff_student', 0),
            'bst_authorities': profile_roles.get('staff_student', 0),
            'academics': profile_roles.get('teacher', 0),
            'alumni': Alumni.objects.count(),
            'projects': projects.count(),
            'pending_projects': projects.filter(approval_status='pending').count(),
            'active_projects': active_projects,
            'completed_projects': completed_projects,
            'open_project_requests': ProjectRequest.objects.filter(status='open').count(),
            'pending_news': pending_news,
            'approved_news': Article.objects.filter(is_approved=True).count(),
            'upcoming_events': Event.objects.filter(is_active=True, start_date__gte=now).count(),
            'pending_opportunities': Opportunity.objects.filter(approval_status='pending').count(),
            'active_opportunities': Opportunity.objects.filter(approval_status='approved', is_active=True).count(),
            'pending_mentorship': MentorshipRequest.objects.filter(status='pending').count(),
            'pending_collaboration': pending_collaborations,
            'open_reports': pending_reports,
            'pending_websites': pending_websites,
            'pending_alumni': pending_alumni,
            'pending_moderation': pending_reports + pending_websites + pending_alumni + pending_collaborations,
            'pending_operations': (
                pending_reports + pending_websites + pending_alumni + pending_collaborations + pending_news
            ),
            'teams': Team.objects.count(),
            'awarded_projects': ProjectAchievement.objects.filter(
                achievement_type__in=['award', 'finalist', 'ranking', 'funded']
            ).values('project_id').distinct().count(),
        },
        'class_distribution': _distribution(class_profiles, 'class_level', Profile.CLASS_CHOICES),
        'technology_distribution': technology_rows,
        'category_distribution': category_rows,
        'project_ratio': {
            'active': active_projects, 'completed': completed_projects,
            'active_percent': round(active_projects / ratio_total * 100) if ratio_total else 0,
            'completed_percent': round(completed_projects / ratio_total * 100) if ratio_total else 0,
        },
        'pending_breakdown': [
            {'key': 'alumni', 'label': 'Mezun talepleri', 'count': pending_alumni},
            {'key': 'website', 'label': 'Site incelemeleri', 'count': pending_websites},
            {'key': 'moderation', 'label': 'Kullanıcı moderasyonu', 'count': pending_reports},
            {'key': 'collaboration', 'label': 'İş birliği talepleri', 'count': pending_collaborations},
            {'key': 'news', 'label': 'Haber onayları', 'count': pending_news},
        ],
    }
