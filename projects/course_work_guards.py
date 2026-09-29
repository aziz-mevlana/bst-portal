"""Serialize legacy project mutation endpoints with course lifecycle operations."""
from functools import wraps

from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect

from .course_work_models import CourseProjectAssignment, CourseProjectWork
from .course_work_services import can_view_work


def course_project_mutation(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        from .models import (ProjectMedia, ProjectAchievement, ProjectContribution,
                             ProjectWritingSuggestion, ProjectComment)
        project_id = kwargs.get('project_id')
        for key, model in (('media_id', ProjectMedia), ('achievement_id', ProjectAchievement),
                           ('contribution_id', ProjectContribution), ('suggestion_id', ProjectWritingSuggestion),
                           ('comment_id', ProjectComment)):
            if key in kwargs:
                project_id = model.objects.filter(pk=kwargs[key]).values_list('project_id', flat=True).first()
                break
        work = CourseProjectWork.objects.filter(project_id=project_id).select_related('assignment').first()
        if not work:
            return view(request, *args, **kwargs)
        with transaction.atomic():
            try:
                assignment = CourseProjectAssignment.objects.select_for_update().get(pk=work.assignment_id)
            except CourseProjectAssignment.DoesNotExist:
                raise Http404
            work.assignment = assignment
            if not can_view_work(request.user, work):
                raise Http404
            if not assignment.is_active:
                if request.method == 'GET':
                    return redirect('projects:course_work_detail', work.pk)
                raise Http404('İptal edilmiş çalışmanın geçmişi salt okunurdur.')
            return view(request, *args, **kwargs)
    return guarded
