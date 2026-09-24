from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from accounts.policies import is_admin, is_bst_authority, is_teacher
from core.audit import record_audit_event
from projects.models import Course, CourseCatalogEntry, CourseInstructor


def can_manage_courses(user):
    return is_admin(user) or is_bst_authority(user)


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ('code', 'name', 'slug', 'description', 'is_active')


@login_required
def course_list(request):
    if not (can_manage_courses(request.user) or is_teacher(request.user)):
        raise PermissionDenied
    entries = CourseCatalogEntry.objects.filter(academic_year='2026-2027', is_active=True)
    if not can_manage_courses(request.user):
        entries = entries.filter(course__instructor_assignments__instructor=request.user,
                                 course__instructor_assignments__is_active=True)
    entries = entries.select_related('course').prefetch_related(
        'course__instructor_assignments__instructor').annotate(
            project_count=Count('course__projects', distinct=True)).distinct().order_by(
                'semester', 'class_level', 'course__code')
    teachers = get_user_model().objects.filter(profile__user_type='teacher', is_active=True).order_by('first_name', 'last_name', 'username') if can_manage_courses(request.user) else []
    return render(request, 'dashboard/courses.html', {'entries': entries, 'teachers': teachers,
                                                       'can_manage_courses': can_manage_courses(request.user)})


@login_required
@transaction.atomic
def course_edit(request, course_id=None):
    if not can_manage_courses(request.user):
        raise PermissionDenied
    course = get_object_or_404(Course, pk=course_id) if course_id else None
    form = CourseForm(request.POST or None, instance=course)
    if request.method == 'POST' and form.is_valid():
        created = course is None
        course = form.save()
        record_audit_event(actor=request.user, action='course.created' if created else 'course.updated', target=course, request=request)
        return redirect('dashboard:courses')
    return render(request, 'dashboard/course_form.html', {'form': form, 'course': course})


@login_required
@require_POST
@transaction.atomic
def course_instructor_change(request, course_id):
    if not can_manage_courses(request.user):
        raise PermissionDenied
    course = get_object_or_404(Course, pk=course_id)
    if request.POST.get('action') not in {'assign', 'remove'}:
        raise PermissionDenied
    instructor_id = request.POST.get('instructor_id', '')
    if not instructor_id.isdigit():
        messages.error(request, 'Geçerli bir akademisyen seçin.')
        return redirect('dashboard:courses')
    user = get_object_or_404(get_user_model(), pk=instructor_id)
    active = request.POST.get('action') == 'assign'
    try:
        assignment = CourseInstructor.objects.filter(course=course, instructor=user).first()
        if assignment and assignment.is_active == active:
            return redirect('dashboard:courses')
        if assignment:
            assignment.is_active = active
            assignment.save(update_fields=['is_active'])
        elif active:
            assignment = CourseInstructor.objects.create(course=course, instructor=user)
        else:
            return redirect('dashboard:courses')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        return redirect('dashboard:courses')
    record_audit_event(actor=request.user, action='course.instructor.assigned' if active else 'course.instructor.removed',
                       target=assignment, metadata={'course_id': course.pk, 'instructor_id': user.pk}, request=request)
    return redirect('dashboard:courses')
