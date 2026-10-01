"""Personal course templates copy definitions only; never live-bind assignments."""
from copy import deepcopy
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from core.audit import record_audit_event
from accounts.policies import is_admin, is_teacher
from .course_requirements import validate_requirements
from .course_work_models import CourseProjectTemplate, CourseProjectAssignment
from .course_work_services import can_manage_assignment, locked_assignment, create_assignment, save_checkpoint, add_expectation

BRIEF_FIELDS = ('topic', 'purpose', 'expectations', 'mode', 'min_team_size', 'max_team_size', 'repository_required')
PLAN_FIELDS = {'title', 'description', 'order', 'evidence_requirements', 'scoring_enabled', 'max_points', 'expected_items'}


def can_manage_template(actor, template):
    return actor.is_authenticated and actor.is_active and (is_admin(actor) or is_teacher(actor) and template.owner_id == actor.pk)


def validate_template_plan(plan):
    if not isinstance(plan, list) or len(plan) > 100:
        raise ValidationError('Şablon en fazla 100 kontrol noktası içerebilir.')
    orders = set()
    for item in plan:
        if not isinstance(item, dict) or set(item) != PLAN_FIELDS:
            raise ValidationError('Geçersiz şablon kontrol noktası.')
        for key, limit in (('title', 200), ('description', 10000)):
            if not isinstance(item[key], str) or len(item[key]) > limit or key == 'title' and not item[key].strip():
                raise ValidationError('Kontrol noktası başlığı/açıklaması geçersiz.')
        if type(item['order']) is not int or not 1 <= item['order'] <= 32767 or item['order'] in orders:
            raise ValidationError('Kontrol noktası sıraları benzersiz pozitif sayılar olmalıdır.')
        orders.add(item['order'])
        validate_requirements(item['evidence_requirements'])
        if type(item['scoring_enabled']) is not bool or type(item['max_points']) is not int or not 1 <= item['max_points'] <= 32767:
            raise ValidationError('Geçersiz şablon puanlama ayarı.')
        expected = item['expected_items']
        if not isinstance(expected, list) or len(expected) > 100 or any(not isinstance(x,str) or not x.strip() or len(x)>300 for x in expected):
            raise ValidationError('Geçersiz beklenenler listesi.')


@transaction.atomic
def save_template(*, actor, values, template=None, expected_version=None):
    if not actor.is_active or not (is_teacher(actor) or is_admin(actor)):
        raise PermissionDenied
    if set(values) - {*BRIEF_FIELDS, 'name', 'plan', 'is_archived'}:
        raise ValidationError('Geçersiz şablon alanı.')
    if template:
        template = CourseProjectTemplate.objects.select_for_update().get(pk=template.pk)
        if not can_manage_template(actor, template):
            raise PermissionDenied
        if expected_version != template.version:
            raise ValidationError('Şablon değişti. Sayfayı yenileyin.')
        template.version += 1
    else:
        template = CourseProjectTemplate(owner=actor)
    for key, value in values.items():
        setattr(template, key, deepcopy(value))
    template.save()
    record_audit_event(actor=actor, action='course.template_saved', target=template)
    return template


@transaction.atomic
def template_from_assignment(*, actor, assignment, name):
    assignment = locked_assignment(assignment.pk)
    if not can_manage_assignment(actor, assignment):
        raise PermissionDenied
    plan = []
    for checkpoint in assignment.checkpoints.filter(is_active=True).prefetch_related('expected_items'):
        plan.append({key: deepcopy(getattr(checkpoint, key)) for key in PLAN_FIELDS - {'expected_items'}})
        plan[-1]['expected_items'] = [item.title for item in checkpoint.expected_items.all()]
    return save_template(actor=actor, values={**{key: getattr(assignment,key) for key in BRIEF_FIELDS}, 'name': name, 'plan': plan})


@transaction.atomic
def create_assignment_with_plan(*, instructor, course, plan, creation_token, template=None, **values):
    """Serialize creation retries on the teacher row; token is scoped to its owner."""
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=instructor.pk)
    try:
        creation_token = uuid.UUID(str(creation_token))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError('Geçersiz oluşturma anahtarı.')
    existing = CourseProjectAssignment.objects.filter(instructor=instructor, creation_token=creation_token).first()
    if existing:
        return existing
    if template:
        template = CourseProjectTemplate.objects.select_for_update().get(pk=template.pk)
        if not can_manage_template(instructor, template) or template.is_archived:
            raise PermissionDenied
    # Validate the submitted, editable snapshot even when a template was used.
    for item in plan:
        due = item.get('due_at')
        if due is None or not values['starts_at'] <= due <= values['ends_at']:
            raise ValidationError('Her kontrol noktası için yeni proje aralığında son tarih seçin.')
    definitions = [{key: value for key, value in item.items() if key != 'due_at'} for item in plan]
    validate_template_plan(definitions)
    assignment = create_assignment(instructor=instructor, course=course, creation_token=creation_token, **values)
    for item in plan:
        checkpoint = save_checkpoint(assignment=assignment, actor=instructor,
            values={key: value for key, value in item.items() if key != 'expected_items'})
        for title in item['expected_items']:
            add_expectation(checkpoint=checkpoint, actor=instructor, title=title)
    return assignment
