from django.db.models import Count, Q
from .models import Project


def apply_project_filters(queryset, params, *, category_ids=(), technology_ids=(), dashboard=False):
    query = params.get('q', '').strip()
    if query:
        queryset = queryset.filter(Q(title__icontains=query) | Q(description__icontains=query))
    for category_id in category_ids:
        queryset = queryset.filter(categories__id=category_id)
    for technology_id in technology_ids:
        queryset = queryset.filter(technologies__id=technology_id)
    status = params.get('status', '')
    if status:
        queryset = queryset.filter(**{'status' if dashboard else 'development_status': status})
    course = params.get('course', '')
    if course:
        queryset = queryset.filter(course__slug=course)
    if dashboard:
        request_id = params.get('project_request', '')
        if request_id.isdigit():
            queryset = queryset.filter(project_request_id=request_id)
    else:
        type_id = params.get('type', '')
        program_id = params.get('program', '')
        if type_id.isdigit():
            queryset = queryset.filter(project_type_id=type_id)
        if params.get('source'):
            queryset = queryset.filter(creation_source=params['source'])
        if program_id.isdigit():
            queryset = queryset.filter(program_participations__program_id=program_id)
        queryset = queryset.annotate(like_count=Count('likes', distinct=True))
        queryset = queryset.order_by('-like_count', '-created_at', '-pk') if params.get('sort') == 'liked' else queryset.order_by('-created_at', '-pk')
    return queryset.distinct()


def requested_view(params):
    view = params.get('view')
    return view if view in {'grid', 'list'} else 'grid'
