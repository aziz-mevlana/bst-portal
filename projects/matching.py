from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from career.models import MentorshipProfile


MATCH_WEIGHTS = {
    'technology': 40,
    'interest': 20,
    'availability': 20,
    'experience': 20,
}


def _ratio_score(required_ids, candidate_ids, weight):
    if not required_ids:
        return 0, set()
    matched = required_ids & candidate_ids
    return round(weight * len(matched) / len(required_ids)), matched


def _project_requirements(project):
    technologies = {item.pk: item.name for item in project.technologies.all()}
    categories = {item.pk: item.name for item in project.categories.all()}
    return technologies, categories


def _candidate_result(kind, candidate_id, name, url, technology_score, interest_score,
                      availability_score, experience_score, matched_tech, matched_categories,
                      missing):
    breakdown = {
        'technology': technology_score,
        'interest': interest_score,
        'availability': availability_score,
        'experience': experience_score,
    }
    return {
        'kind': kind,
        'id': candidate_id,
        'name': name,
        'url': url,
        'score': sum(breakdown.values()),
        'breakdown': breakdown,
        'matched_technologies': sorted(matched_tech),
        'matched_categories': sorted(matched_categories),
        'missing': missing,
    }


def rank_student_matches(project, limit=10):
    tech_map, category_map = _project_requirements(project)
    candidates = User.objects.filter(
        is_active=True,
        profile__user_type='student',
        profile__is_portfolio_public=True,
        profile__is_open_to_team_offers=True,
    ).exclude(Q(pk=project.created_by_id) | Q(pk__in=project.team.values('pk'))).select_related(
        'profile'
    ).prefetch_related('profile__technologies', 'profile__categories').annotate(
        team_project_count=Count('projects', distinct=True),
        owned_project_count=Count('created_projects', distinct=True),
    )

    results = []
    for user in candidates:
        candidate_tech = {item.pk: item.name for item in user.profile.technologies.all()}
        candidate_categories = {item.pk: item.name for item in user.profile.categories.all()}
        tech_score, tech_ids = _ratio_score(set(tech_map), set(candidate_tech), MATCH_WEIGHTS['technology'])
        interest_score, category_ids = _ratio_score(set(category_map), set(candidate_categories), MATCH_WEIGHTS['interest'])
        experience_count = user.team_project_count + user.owned_project_count
        experience_score = round(MATCH_WEIGHTS['experience'] * min(experience_count, 3) / 3)
        missing = []
        if tech_score < MATCH_WEIGHTS['technology']:
            missing.append('Bazı proje teknolojileri profilde yer almıyor.')
        if interest_score < MATCH_WEIGHTS['interest']:
            missing.append('İlgi alanı eşleşmesi sınırlı.')
        results.append(_candidate_result(
            'student', user.pk, user.get_full_name() or user.username,
            user.profile.get_absolute_url(), tech_score, interest_score,
            MATCH_WEIGHTS['availability'], experience_score,
            [candidate_tech[pk] for pk in tech_ids],
            [candidate_categories[pk] for pk in category_ids], missing,
        ))
    return sorted(results, key=lambda item: (-item['score'], item['name']))[:limit]


def rank_advisor_matches(project, limit=10):
    tech_map, category_map = _project_requirements(project)
    candidates = User.objects.filter(
        is_active=True,
        profile__user_type='teacher',
    ).exclude(pk=project.advisor_id).select_related('profile').prefetch_related(
        'profile__technologies', 'profile__categories'
    ).annotate(
        advised_project_count=Count('advised_projects', distinct=True),
        active_advised_count=Count(
            'advised_projects',
            filter=Q(advised_projects__development_status__in=['idea', 'planning', 'in_progress']),
            distinct=True,
        ),
    )

    results = []
    for user in candidates:
        candidate_tech = {item.pk: item.name for item in user.profile.technologies.all()}
        candidate_categories = {item.pk: item.name for item in user.profile.categories.all()}
        tech_score, tech_ids = _ratio_score(set(tech_map), set(candidate_tech), MATCH_WEIGHTS['technology'])
        interest_score, category_ids = _ratio_score(set(category_map), set(candidate_categories), MATCH_WEIGHTS['interest'])
        availability_score = 20 if user.active_advised_count < 5 else 10 if user.active_advised_count < 10 else 0
        experience_score = round(MATCH_WEIGHTS['experience'] * min(user.advised_project_count, 3) / 3)
        missing = []
        if availability_score < 20:
            missing.append('Aktif danışmanlık yükü yüksek olabilir.')
        if not tech_ids:
            missing.append('Doğrudan teknoloji eşleşmesi bulunamadı.')
        results.append(_candidate_result(
            'advisor', user.pk, user.get_full_name() or user.username,
            reverse('accounts:user_profile', kwargs={'user_id': user.pk}), tech_score, interest_score,
            availability_score, experience_score,
            [candidate_tech[pk] for pk in tech_ids],
            [candidate_categories[pk] for pk in category_ids], missing,
        ))
    return sorted(results, key=lambda item: (-item['score'], item['name']))[:limit]


def rank_mentor_matches(project, limit=10):
    tech_map, category_map = _project_requirements(project)
    now = timezone.localdate()
    candidates = MentorshipProfile.objects.filter(
        is_available=True,
        alumni__is_show_in_alumni_list=True,
    ).select_related('alumni', 'alumni__user').prefetch_related(
        'mentoring_topics', 'alumni__technologies'
    ).annotate(
        active_request_count=Count(
            'requests',
            filter=Q(requests__status__in=['pending', 'accepted'], requests__created_at__year=now.year,
                     requests__created_at__month=now.month),
            distinct=True,
        ),
        experience_count=Count('alumni__work_experiences', distinct=True),
    )

    results = []
    for mentor in candidates:
        candidate_tech = {item.pk: item.name for item in mentor.alumni.technologies.all()}
        candidate_categories = {item.pk: item.name for item in mentor.mentoring_topics.all()}
        tech_score, tech_ids = _ratio_score(set(tech_map), set(candidate_tech), MATCH_WEIGHTS['technology'])
        interest_score, category_ids = _ratio_score(set(category_map), set(candidate_categories), MATCH_WEIGHTS['interest'])
        availability_score = MATCH_WEIGHTS['availability'] if mentor.active_request_count < mentor.monthly_capacity else 0
        experience_score = round(MATCH_WEIGHTS['experience'] * min(mentor.experience_count, 3) / 3)
        alumni = mentor.alumni
        if alumni.user_id and alumni.user.username:
            url = reverse('alumni:alumni_detail', kwargs={'username': alumni.user.username})
        else:
            url = reverse('alumni:alumni_detail_by_id', kwargs={'alumni_id': alumni.pk})
        missing = []
        if not availability_score:
            missing.append('Bu ayki mentorluk kapasitesi dolu.')
        if not category_ids:
            missing.append('Mentorluk konusu eşleşmesi bulunamadı.')
        results.append(_candidate_result(
            'mentor', mentor.pk, alumni.get_display_name(), url,
            tech_score, interest_score, availability_score, experience_score,
            [candidate_tech[pk] for pk in tech_ids],
            [candidate_categories[pk] for pk in category_ids], missing,
        ))
    return sorted(results, key=lambda item: (-item['score'], item['name']))[:limit]


def rank_all_matches(project):
    return {
        'students': rank_student_matches(project),
        'advisors': rank_advisor_matches(project),
        'mentors': rank_mentor_matches(project),
        'weights': MATCH_WEIGHTS,
    }
