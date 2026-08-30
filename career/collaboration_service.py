from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from projects.models import ProjectRequest

from .models import CollaborationRequest, Opportunity


PROJECT_REQUEST_TYPES = {'project', 'team', 'capstone', 'research'}
CAREER_REQUEST_TYPES = {'internship', 'recruitment'}


@transaction.atomic
def publish_collaboration(collaboration_id, reviewer):
    item = CollaborationRequest.objects.select_for_update().get(pk=collaboration_id)
    if not (reviewer.is_staff or reviewer.is_superuser):
        raise ValidationError('Bu işlem yalnızca gerçek yöneticiler tarafından yapılabilir.')
    if not item.email_verified_at:
        raise ValidationError('E-posta adresi doğrulanmadan talep yayımlanamaz.')

    if item.request_type in PROJECT_REQUEST_TYPES:
        if item.project_request_id:
            return item.project_request
        if not item.assigned_teacher_id or not item.project_type_id:
            raise ValidationError('Proje ilanı için sorumlu akademisyen ve proje türü zorunludur.')
        project_request = ProjectRequest.objects.create(
            title=item.normalized_title or item.title,
            description=item.normalized_description or item.description,
            expected_output=item.expected_output,
            deadline=item.deadline,
            teacher=item.assigned_teacher,
            project_type=item.project_type,
            status='open',
        )
        project_request.categories.set(item.categories.all())
        project_request.technologies.set(item.technologies.all())
        item.project_request = project_request
        item.publication_channel = 'project'
        result = project_request
    elif item.request_type in CAREER_REQUEST_TYPES:
        if item.opportunity_id:
            return item.opportunity
        opportunity = Opportunity.objects.create(
            title=item.normalized_title or item.title,
            opportunity_type='internship' if item.request_type == 'internship' else 'full_time',
            organization=item.organization,
            description=item.normalized_description or item.description,
            requirements=item.expected_output,
            work_mode='remote',
            contact_method='email',
            contact_email=item.email,
            deadline=item.deadline,
            created_by=reviewer,
            approval_status='approved',
            approved_by=reviewer,
            approved_at=timezone.now(),
        )
        opportunity.technologies.set(item.technologies.all())
        item.opportunity = opportunity
        item.publication_channel = 'career'
        result = opportunity
    else:
        item.publication_channel = item.publication_channel or 'internal'
        result = item

    item.status = 'published'
    item.reviewed_by = reviewer
    item.reviewed_at = timezone.now()
    item.save(update_fields=[
        'project_request', 'opportunity', 'publication_channel', 'status',
        'reviewed_by', 'reviewed_at', 'updated_at',
    ])
    return result
