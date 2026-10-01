from copy import deepcopy
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from accounts.policies import is_admin, is_teacher
from .course_work_models import CourseProjectTemplate
from .course_work_forms import CourseProjectTemplateForm, CoursePlanFormSet
from .course_template_services import can_manage_template, save_template, template_from_assignment
from .course_work_views import _assignment


def teacher(user):
    if not user.is_active or not (is_teacher(user) or is_admin(user)):
        raise Http404


def owned_template(user, pk):
    raw = str(pk)
    if not raw.isascii() or not raw.isdigit() or not 0 < int(raw) < 2**63:
        raise Http404
    template = get_object_or_404(CourseProjectTemplate, pk=pk)
    if not can_manage_template(user, template):
        raise Http404
    return template


def plan_initial(plan):
    return [{**deepcopy(item), 'expected_items': '\n'.join(item['expected_items'])} for item in plan]


def cleaned_plan(formset):
    return [{key: value for key, value in form.cleaned_data.items() if key != 'DELETE'}
            for form in formset.forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]


@login_required
@require_GET
def template_list(request):
    teacher(request.user)
    templates = CourseProjectTemplate.objects.all() if is_admin(request.user) else CourseProjectTemplate.objects.filter(owner=request.user)
    return render(request, 'projects/course_template_list.html', {'templates': templates.select_related('owner').order_by('is_archived','name')})


@login_required
@require_http_methods(['GET','POST'])
def template_edit(request, template_id=None):
    teacher(request.user)
    template = owned_template(request.user, template_id) if template_id else None
    form = CourseProjectTemplateForm(request.POST or None, instance=template)
    formset = CoursePlanFormSet(request.POST or None, prefix='plan', initial=plan_initial(template.plan) if template else [], form_kwargs={'include_dates': False})
    if request.method == 'POST':
        valid = form.is_valid(); plan_valid = formset.is_valid()
        if valid and plan_valid:
            try:
                values = {key: value for key,value in form.cleaned_data.items() if key != 'version'}
                save_template(actor=request.user, template=template, expected_version=form.cleaned_data['version'], values={**values, 'plan': cleaned_plan(formset)})
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, exc)
            else:
                return redirect('projects:course_template_list')
    return render(request, 'projects/course_template_form.html', {'form': form, 'plan_formset': formset, 'template': template})


@login_required
@require_POST
def template_archive(request, template_id):
    template = owned_template(request.user, template_id)
    try:
        version = int(request.POST.get('version',''))
        save_template(actor=request.user, template=template, expected_version=version, values={'is_archived': True})
    except (ValueError, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect('projects:course_template_list')


@login_required
@require_http_methods(['GET','POST'])
def assignment_to_template(request, assignment_id):
    assignment = _assignment(request.user, assignment_id)
    from django import forms
    class NameForm(forms.Form):
        name = forms.CharField(label='Şablon adı', max_length=200)
    form = NameForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        template_from_assignment(actor=request.user, assignment=assignment, name=form.cleaned_data['name'])
        return redirect('projects:course_template_list')
    return render(request, 'projects/course_save_template.html', {'assignment': assignment, 'form': form})
