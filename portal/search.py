"""Validated filters shared by full search and the navbar's inline results."""
from urllib.parse import urlencode

from django import forms
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.models import Profile
from alumni.models import Alumni
from career.models import Opportunity
from core.analytics import record_analytics_event
from events.models import Event
from news.models import Article
from projects.models import Project, ProjectCategory, ProjectProgram, ProjectType, Technology


TABS = [
    ('all', 'Tümü'), ('projects', 'Projeler'), ('talent', 'Yetenekler'),
    ('academics', 'Akademisyenler'), ('alumni', 'Mezunlar'),
    ('events', 'Etkinlikler'), ('news', 'Haberler'), ('career', 'Kariyer'),
]


class SearchForm(forms.Form):
    q = forms.CharField(label='Aranacak ifade', required=False, max_length=120,
                        widget=forms.SearchInput(attrs={'placeholder': 'Proje, kişi, şirket veya etkinlik ara…'}))
    tab = forms.ChoiceField(choices=TABS, required=False, widget=forms.HiddenInput)
    technology = forms.ModelChoiceField(label='Teknoloji', required=False,
        queryset=Technology.objects.filter(is_active=True), empty_label='Tüm teknolojiler')
    category = forms.ModelChoiceField(label='Kategori', required=False,
        queryset=ProjectCategory.objects.filter(is_active=True), empty_label='Tüm kategoriler')
    type = forms.ModelChoiceField(label='Proje türü', required=False,
        queryset=ProjectType.objects.filter(is_active=True), empty_label='Tüm proje türleri')
    program = forms.ModelChoiceField(label='Program', required=False,
        queryset=ProjectProgram.objects.filter(is_active=True), empty_label='Tüm programlar')
    status = forms.ChoiceField(label='Proje durumu', required=False,
        choices=[('', 'Tüm durumlar')] + list(Project.DEVELOPMENT_STATUS_CHOICES))
    source = forms.ChoiceField(label='Proje kaynağı', required=False,
        choices=[('', 'Tüm kaynaklar')] + [choice for choice in Project.CREATION_SOURCE_CHOICES if choice[0] != 'LEGACY'])
    class_level = forms.ChoiceField(label='Sınıf', required=False,
        choices=[('', 'Tüm sınıflar')] + list(Profile.CLASS_CHOICES))
    graduation_year = forms.IntegerField(label='Mezuniyet yılı', required=False, min_value=1900, max_value=2100,
        widget=forms.NumberInput(attrs={'placeholder': 'Örn. 2026'}))
    availability = forms.ChoiceField(label='Uygunluk', required=False, choices=[
        ('', 'Tüm uygunluklar'), ('job', 'İş arıyor'), ('internship', 'Staj arıyor'),
        ('team', 'Ekip tekliflerine açık'), ('mentoring', 'Mentorluğa açık'),
    ])
    sort = forms.ChoiceField(label='Sıralama', required=False,
        choices=[('', 'En yeni'), ('title', 'İsme göre A–Z')])

    @property
    def filters(self):
        return [field for field in self.visible_fields() if field.name != 'q']


def text_search(queryset, query, fields):
    # Each word must match; words may occur in different fields (e.g. first + last name).
    for word in query.split()[:12]:
        predicate = Q()
        for field in fields:
            predicate |= Q(**{f'{field}__icontains': word})
        queryset = queryset.filter(predicate)
    return queryset


def search_querysets(user, data, has_search):
    people = Profile.objects.filter(user__is_active=True, show_in_search=True, account_status='active')
    sets = {
        'projects': Project.objects.filter(visibility='public', approval_status='approved').select_related('project_type'),
        'talent': people.filter(user_type__in=['student', 'staff_student'], user__is_staff=False,
                               user__is_superuser=False, is_portfolio_public=True).select_related('user'),
        'academics': people.filter(user_type='teacher').select_related('user'),
        'alumni': Alumni.objects.filter(is_show_in_alumni_list=True).select_related('user'),
        'events': Event.objects.filter(is_active=True),
        'news': Article.objects.public(),
        'career': Opportunity.objects.filter(approval_status='approved', is_active=True).filter(
            Q(deadline__isnull=True) | Q(deadline__gte=timezone.localdate())),
    }
    fields = {
        'projects': ['title', 'description', 'expected_output'],
        'talent': ['user__first_name', 'user__last_name', 'headline', 'bio'],
        'academics': ['user__first_name', 'user__last_name', 'headline', 'bio'],
        'alumni': ['full_name', 'user__first_name', 'user__last_name', 'current_position', 'company', 'bio'],
        'events': ['title', 'description', 'location'], 'news': ['title', 'summary'],
        'career': ['title', 'organization', 'description', 'requirements'],
    }
    active_scopes = set(sets)
    for name, relation, scopes in [
        ('technology', 'technologies', {'projects', 'talent', 'academics', 'alumni', 'career'}),
        ('category', 'categories', {'projects', 'talent', 'academics', 'alumni'}),
        ('type', 'project_type', {'projects'}), ('program', 'program_participations__program', {'projects'}),
        ('status', 'development_status', {'projects'}), ('source', 'creation_source', {'projects'}),
        ('class_level', 'class_level', {'talent'}), ('graduation_year', 'graduation_year', {'talent', 'alumni'}),
    ]:
        if data.get(name):
            active_scopes &= scopes
            for scope in scopes:
                sets[scope] = sets[scope].filter(**{relation: data[name]})
    availability = data.get('availability')
    if availability:
        active_scopes &= {'talent', 'alumni'} if availability == 'mentoring' else {'talent'}
        profile_field = {
            'job': 'is_looking_for_job', 'internship': 'is_looking_for_internship',
            'team': 'is_open_to_team_offers', 'mentoring': 'is_open_to_mentoring',
        }[availability]
        sets['talent'] = sets['talent'].filter(**{profile_field: True})
        if availability == 'mentoring':
            sets['alumni'] = sets['alumni'].filter(is_available_for_mentoring=True)
    if data.get('class_level'):
        sets['talent'] = sets['talent'].filter(show_class_level=True)
    if not user.is_authenticated:
        active_scopes.discard('alumni')
    ordering = {
        'projects': '-created_at', 'talent': '-user__date_joined', 'academics': '-user__date_joined',
        'alumni': '-graduation_year', 'events': '-start_date', 'news': '-date', 'career': '-created_at',
    }
    titles = {'talent': 'user__first_name', 'academics': 'user__first_name', 'alumni': 'full_name'}
    for scope, queryset in sets.items():
        if not has_search or scope not in active_scopes:
            sets[scope] = queryset.none()
        else:
            order = titles.get(scope, 'title') if data.get('sort') == 'title' else ordering[scope]
            sets[scope] = text_search(queryset, data.get('q', ''), fields[scope]).distinct().order_by(order, 'pk')
    return sets


def result_card(scope, item):
    if scope in {'talent', 'academics'}:
        url = item.get_absolute_url() if scope == 'talent' else f"{reverse('portal:academic_list')}#academic-{item.pk}"
        return {'label': item.user.get_full_name() or item.user.username, 'subtitle': item.headline, 'url': url}
    if scope == 'alumni':
        url = (reverse('alumni:alumni_detail', args=[item.user.username]) if item.user_id
               else reverse('alumni:alumni_detail_by_id', args=[item.pk]))
        item.search_url = url
        return {'label': item.get_display_name(), 'subtitle': ' · '.join(filter(None, [item.current_position, item.company])), 'url': url}
    if scope == 'events':
        return {'label': item.title, 'subtitle': item.location, 'url': reverse('events:event_detail', args=[item.pk])}
    return {'label': item.title, 'subtitle': getattr(item, 'summary', '') or getattr(item, 'organization', '') or getattr(item, 'description', ''),
            'url': item.get_absolute_url()}


@never_cache
@require_GET
def global_search(request):
    form = SearchForm(request.GET)
    valid = form.is_valid()
    data = form.cleaned_data if valid else {}
    query = data.get('q', '')
    active_tab = data.get('tab') or 'all'
    has_filters = any(data.get(key) for key in form.fields if key not in {'q', 'tab', 'sort'})
    has_search = valid and bool(query or has_filters)
    json_mode = request.GET.get('format') == 'json'
    if json_mode and (not valid or len(query) < 2):
        return JsonResponse({'results': [], 'errors': form.errors.get_json_data()}, status=400 if not valid else 200)
    sets = search_querysets(request.user, data, has_search)
    counts = {scope: queryset.count() for scope, queryset in sets.items()}
    total = sum(counts.values())
    params = {key: request.GET[key] for key in form.fields if request.GET.get(key)}

    def link(**changes):
        return '?' + urlencode({**params, **changes})

    if json_mode:
        groups = []
        for scope, label in TABS[1:]:
            if active_tab not in {'all', scope}:
                continue
            groups.append([{**result_card(scope, item), 'category': label} for item in sets[scope][:8]])
        # Round-robin categories keeps the preview useful across content types.
        results = [group[index] for index in range(8) for group in groups if len(group) > index]
        return JsonResponse({'results': results[:8], 'total': total if active_tab == 'all' else counts[active_tab],
                             'full_url': reverse('portal:global_search') + link()})
    result_sets = {scope: [] for scope in sets}
    page = None
    sections = []
    for scope, label in TABS[1:]:
        if active_tab not in {'all', scope}:
            continue
        if active_tab == 'all':
            items = list(sets[scope][:6])
        else:
            page = Paginator(sets[scope], 12).get_page(request.GET.get('page'))
            items = list(page.object_list)
        cards = [result_card(scope, item) for item in items]
        result_sets[scope] = items
        if cards:
            sections.append({'label': label, 'cards': cards, 'count': counts[scope], 'more_url': link(tab=scope), 'has_more': active_tab == 'all' and counts[scope] > 6})
    total_visible = total if active_tab == 'all' else counts[active_tab]
    if has_search:
        record_analytics_event(request, event_type='search', succeeded=total_visible > 0,
                               metadata={'result_count': total_visible, 'query_length': len(query)})
    return render(request, 'portal/global_search.html', {
        'form': form, 'query': query, 'active_tab': active_tab, 'result_sets': result_sets,
        'sections': sections, 'total_visible': total_visible, 'has_search': has_search, 'has_filters': has_filters,
        'tabs': [{'key': key, 'label': label, 'url': link(tab=key), 'count': total if key == 'all' else counts[key]} for key, label in TABS],
        'page_obj': page, 'previous_url': link(page=page.previous_page_number()) if page and page.has_previous() else '',
        'next_url': link(page=page.next_page_number()) if page and page.has_next() else '',
        'meta_robots': 'noindex,follow',
    })
