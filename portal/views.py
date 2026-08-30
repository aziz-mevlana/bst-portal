from django.db.models import Count, Q
from django.urls import reverse
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.models import Profile
from alumni.models import Alumni
from career.models import Opportunity
from core.analytics import record_analytics_event
from events.models import Event
from news.models import Article
from projects.models import (
    Project,
    ProjectCategory,
    ProjectContribution,
    ProjectFeature,
    ProjectRequest,
    TeamOpenRole,
    Technology,
    ProjectProgram,
    ProjectType,
)


def _clean_company_statistics():
    noise_terms = (
        'tam zamanlı', 'yarı zamanlı', 'serbest çalışan', 'stajyer',
        'linkedin bu işi', 'halen', ' yıl', ' ay', 'insan kaynakları hizmetleri',
    )
    candidates = Alumni.objects.exclude(company='').values('company').annotate(total=Count('id')).order_by('-total', 'company')
    cleaned = []
    for item in candidates:
        company = item['company'].strip()
        normalized = company.casefold()
        if not company or len(company) > 90 or any(term in normalized for term in noise_terms):
            continue
        if any(char.isdigit() for char in company) and len(company.split()) <= 3:
            continue
        cleaned.append({'company': company, 'total': item['total']})
    return cleaned


class IndexView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        public_projects = Project.objects.filter(
            visibility='public',
            approval_status='approved',
        ).select_related('project_type', 'created_by').prefetch_related(
            'technologies', 'media', 'team'
        )

        features = ProjectFeature.objects.filter(
            is_active=True,
            project__visibility='public',
            project__approval_status='approved',
        ).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now),
            Q(ends_at__isnull=True) | Q(ends_at__gte=now),
        ).select_related('project', 'project__project_type', 'project__created_by').prefetch_related(
            'project__technologies', 'project__media', 'project__team'
        )[:6]
        featured_projects = [feature.project for feature in features]
        top_liked_projects = list(public_projects.annotate(like_count=Count('likes', distinct=True)).filter(
            like_count__gt=0
        ).order_by('-like_count', '-created_at')[:6])
        awarded_projects = list(
            public_projects.filter(achievements__isnull=False).distinct().order_by('-created_at')[:6]
        )

        # The homepage selection is editorial rather than a "latest items" fallback.
        # A project can appear in several signals, but it is rendered only once.
        home_projects = []
        seen_project_ids = set()
        for collection, label in (
            (featured_projects, 'Öne çıkan'),
            (top_liked_projects, 'Topluluğun seçimi'),
            (awarded_projects, 'Başarı hikâyesi'),
        ):
            for project in collection:
                if project.pk in seen_project_ids:
                    continue
                project.home_label = label
                project.home_like_count = getattr(project, 'like_count', None)
                home_projects.append(project)
                seen_project_ids.add(project.pk)
                if len(home_projects) == 6:
                    break
            if len(home_projects) == 6:
                break

        missing_like_ids = [project.pk for project in home_projects if project.home_like_count is None]
        if missing_like_ids:
            like_counts = dict(
                Project.objects.filter(pk__in=missing_like_ids).annotate(
                    total=Count('likes', distinct=True)
                ).values_list('pk', 'total')
            )
            for project in home_projects:
                if project.home_like_count is None:
                    project.home_like_count = like_counts.get(project.pk, 0)

        cover_theme_groups = (
            ({'ai_ml', 'data_science', 'database'}, 'violet'),
            ({'mobile', 'frontend', 'design'}, 'coral'),
            ({'iot', 'robotics', 'cybersecurity'}, 'amber'),
            ({'cloud', 'devops', 'backend'}, 'cyan'),
        )
        for project in home_projects:
            technology_groups = {item.group for item in project.technologies.all()}
            project.home_cover_theme = 'blue'
            for groups, theme in cover_theme_groups:
                if technology_groups & groups:
                    project.home_cover_theme = theme
                    break

        featured_students = Profile.objects.filter(
            user_type__in={'student', 'staff_student'},
            user__is_active=True,
            user__is_staff=False,
            user__is_superuser=False,
            is_portfolio_public=True,
            show_in_search=True,
        ).filter(
            Q(is_featured=True, featured_from__isnull=True) | Q(is_featured=True, featured_from__lte=now)
        ).filter(
            Q(featured_until__isnull=True) | Q(featured_until__gte=now)
        ).select_related('user').prefetch_related('technologies', 'categories').annotate(
            completed_project_count=Count(
                'user__projects',
                filter=Q(
                    user__projects__visibility='public',
                    user__projects__approval_status='approved',
                    user__projects__development_status='completed',
                ),
                distinct=True,
            )
        ).order_by('featured_order', '-completed_project_count')[:6]
        if not featured_students:
            featured_students = Profile.objects.filter(
                user_type__in={'student', 'staff_student'}, user__is_active=True,
                user__is_staff=False, user__is_superuser=False,
                is_portfolio_public=True, show_in_search=True
            ).select_related('user').prefetch_related('technologies', 'categories').annotate(
                completed_project_count=Count(
                    'user__projects',
                    filter=Q(
                        user__projects__visibility='public',
                        user__projects__approval_status='approved',
                        user__projects__development_status='completed',
                    ),
                    distinct=True,
                )
            ).order_by('-completed_project_count', 'user__first_name')[:6]

        featured_students = list(featured_students)
        upcoming_events = list(
            Event.objects.filter(is_active=True, end_date__gte=now).order_by('start_date')[:4]
        )
        open_opportunities = list(
            Opportunity.objects.filter(approval_status='approved', is_active=True).filter(
                Q(deadline__isnull=True) | Q(deadline__gte=timezone.localdate())
            ).prefetch_related('technologies').order_by('deadline', '-created_at')[:4]
        )
        open_project_requests = list(
            ProjectRequest.objects.filter(status='open', created_project__isnull=True).filter(
                Q(deadline__isnull=True) | Q(deadline__gte=timezone.localdate())
            ).select_related('teacher', 'project_type').prefetch_related('technologies').order_by(
                'deadline', '-created_at'
            )[:4]
        )
        open_team_roles = list(
            TeamOpenRole.objects.filter(
                is_open=True,
                team__recruitment_open=True,
            ).select_related('team').prefetch_related('required_technologies').order_by(
                '-created_at'
            )[:4]
        )
        for request_item in open_project_requests:
            request_item.home_url = reverse('projects:request_detail', args=[request_item.pk])
            request_item.home_kind = 'Proje ilanı'
        for opportunity in open_opportunities:
            opportunity.home_url = opportunity.get_absolute_url()
            opportunity.home_kind = opportunity.get_opportunity_type_display()
        for team_role in open_team_roles:
            team_role.home_url = team_role.team.get_absolute_url()
            team_role.home_kind = 'Açık ekip rolü'

        hero_opportunity = (
            open_project_requests[0] if open_project_requests else (
                open_opportunities[0] if open_opportunities else None
            )
        )

        company_stats = _clean_company_statistics()
        actionable_count = len(open_opportunities) + len(open_project_requests) + len(open_team_roles)
        homepage_stats = {
            'projects': public_projects.count(),
            'students': Profile.objects.filter(
                user_type__in={'student', 'staff_student'}, user__is_active=True,
                user__is_staff=False, user__is_superuser=False,
            ).count(),
            'alumni': Alumni.objects.filter(is_show_in_alumni_list=True).count(),
        }
        if actionable_count:
            homepage_stats['opportunities'] = actionable_count
        else:
            homepage_stats['technologies'] = Technology.objects.filter(is_active=True).count()

        context.update({
            'events': upcoming_events,
            'open_opportunities': open_opportunities,
            'open_project_requests': open_project_requests,
            'open_team_roles': open_team_roles,
            'featured_projects': featured_projects,
            'top_liked_projects': top_liked_projects,
            'awarded_projects': awarded_projects,
            'home_projects': home_projects,
            'hero_project': home_projects[0] if home_projects else None,
            'hero_event': upcoming_events[0] if upcoming_events else None,
            'hero_opportunity': hero_opportunity,
            'hero_team_role': open_team_roles[0] if open_team_roles else None,
            'featured_students': featured_students,
            'academics': Profile.objects.filter(user_type='teacher', user__is_active=True, show_in_search=True).select_related('user').prefetch_related('categories')[:8],
            'top_companies': company_stats[:12],
            'stats': homepage_stats,
            'career_stats': {
                'companies': len(company_stats),
                'mentors': Alumni.objects.filter(is_available_for_mentoring=True).count(),
            },
        })
        return context


def talent_list(request):
    profiles = Profile.objects.filter(
        user_type__in={'student', 'staff_student'},
        user__is_active=True,
        user__is_staff=False,
        user__is_superuser=False,
        is_portfolio_public=True,
        show_in_search=True,
    ).select_related('user').prefetch_related('technologies', 'categories').annotate(
        completed_project_count=Count(
            'user__projects',
            filter=Q(
                user__projects__visibility='public',
                user__projects__approval_status='approved',
                user__projects__development_status='completed',
            ),
            distinct=True,
        )
    )
    query = request.GET.get('q', '').strip()
    technology = request.GET.get('technology', '')
    specialty = request.GET.get('specialty', '')
    class_level = request.GET.get('class_level', '')
    graduation_year = request.GET.get('graduation_year', '')
    availability = request.GET.get('availability', '')
    if query:
        profiles = profiles.filter(
            Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query)
            | Q(headline__icontains=query) | Q(bio__icontains=query)
        )
    if technology:
        profiles = profiles.filter(technologies__id=technology)
    if specialty:
        profiles = profiles.filter(categories__id=specialty)
    if class_level:
        profiles = profiles.filter(class_level=class_level)
    if graduation_year:
        profiles = profiles.filter(graduation_year=graduation_year)
    availability_fields = {
        'job': 'is_looking_for_job',
        'internship': 'is_looking_for_internship',
        'team': 'is_open_to_team_offers',
        'mentoring': 'is_open_to_mentoring',
    }
    if availability in availability_fields:
        profiles = profiles.filter(**{availability_fields[availability]: True})
    profiles = profiles.distinct().order_by('-is_featured', '-completed_project_count', 'user__first_name')
    return render(request, 'portal/talent_list.html', {
        'profiles': profiles,
        'technologies': Technology.objects.filter(is_active=True),
        'specialties': ProjectCategory.objects.filter(is_active=True),
        'class_choices': Profile.CLASS_CHOICES,
        'selected': request.GET,
    })


def academic_list(request):
    academics = Profile.objects.filter(
        user_type='teacher',
        user__is_active=True,
        account_status='active',
        is_portfolio_public=True,
        show_in_search=True,
    ).select_related('user').prefetch_related('categories', 'technologies').order_by(
        'user__first_name', 'user__last_name'
    )
    return render(request, 'portal/academic_list.html', {'academics': academics})


def academic_detail(request, slug):
    profile = get_object_or_404(
        Profile.objects.select_related('user').prefetch_related('categories', 'technologies'),
        public_slug=slug,
        user_type='teacher',
        user__is_active=True,
        account_status='active',
        user__is_staff=False,
        user__is_superuser=False,
    )
    if not profile.is_portfolio_public and request.user != profile.user:
        raise Http404

    projects = profile.showcase_projects.filter(
        visibility='public',
        approval_status='approved',
    ).select_related('project_type').prefetch_related('technologies', 'media').order_by('-updated_at')

    record_analytics_event(request, event_type='profile_view', target=profile, succeeded=True)
    return render(request, 'portal/academic_detail.html', {
        'academic': profile,
        'academic_projects': projects if profile.show_projects else Project.objects.none(),
        'canonical_url': request.build_absolute_uri(profile.get_absolute_url()),
        'meta_title': f'{profile.get_display_title()} {profile.user.get_full_name()} | BST Portal'.strip(),
        'meta_description': (profile.headline or profile.bio or 'BST Akademisyen Profili')[:160],
        'meta_robots': 'index,follow' if profile.is_portfolio_public else 'noindex,nofollow',
    })


def portfolio_detail(request, slug):
    profile = get_object_or_404(
        Profile.objects.select_related('user').prefetch_related('technologies', 'categories', 'certificates'),
        public_slug=slug,
        user_type__in={'student', 'staff_student'},
        user__is_active=True,
        user__is_staff=False,
        user__is_superuser=False,
    )
    if not profile.is_portfolio_public and request.user != profile.user:
        raise Http404

    public_projects = Project.objects.filter(
        Q(created_by=profile.user) | Q(team=profile.user),
        showcased_by_profiles=profile,
        visibility='public',
        approval_status='approved',
        development_status='completed',
    ).select_related('project_type').prefetch_related('technologies', 'media').distinct()
    contributions = ProjectContribution.objects.filter(
        user=profile.user,
        verified_by_owner=True,
        project__visibility='public',
        project__approval_status='approved',
    ).filter(
        Q(project__advisor__isnull=True) | Q(verified_by_advisor=True)
    ).select_related('project', 'project__project_type')

    record_analytics_event(request, event_type='profile_view', target=profile, succeeded=True)

    return render(request, 'portal/portfolio_detail.html', {
        'portfolio': profile,
        'portfolio_projects': public_projects if profile.show_projects else Project.objects.none(),
        'contributions': contributions if profile.show_contributions else ProjectContribution.objects.none(),
        'certificates': profile.certificates.filter(is_public=True),
        'canonical_url': request.build_absolute_uri(profile.get_absolute_url()),
        'meta_title': f'{profile.user.get_full_name() or profile.user.username} | BST Portal',
        'meta_description': (
            profile.headline
            or profile.bio
            or 'BST Bilişim Sistemleri ve Teknolojileri öğrenci portfolyosu'
        )[:160],
        'meta_robots': 'index,follow' if profile.is_portfolio_public else 'noindex,nofollow',
    })
