from urllib.parse import urlparse

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.urls import reverse

from accounts.models import MODERATION_REASON_CHOICES
from accounts.email_service import send_transactional_email
from accounts.policies import can_review_alumni_registration, is_admin
from accounts.validators import validate_github_username, validate_linkedin_slug
from core.audit import record_audit_event
from core.notifications import create_notification

from .models import Alumni, AlumniRegistrationRequest


def _queue_registration_email(subject, message, recipient):
    """Send after commit; an SMTP outage must not roll back reviewed data."""
    def send_safely():
        try:
            send_transactional_email(subject, message, recipient)
        except Exception:
            return

    transaction.on_commit(send_safely)


def _canonical_social_value(url, kind):
    if not url:
        return ''
    parsed = urlparse(url.strip())
    host = (parsed.hostname or '').lower().removeprefix('www.')
    parts = [part for part in parsed.path.split('/') if part]
    if parsed.scheme not in {'http', 'https'} or parsed.query or parsed.fragment:
        return ''
    try:
        if kind == 'github' and host == 'github.com' and len(parts) == 1:
            validate_github_username(parts[0])
            return parts[0]
        if kind == 'linkedin' and host == 'linkedin.com' and len(parts) == 2 and parts[0].lower() == 'in':
            validate_linkedin_slug(parts[1])
            return parts[1]
    except ValidationError:
        return ''
    return ''


def _activate_request(registration, reviewer, alumni, status, request=None):
    user = registration.user
    profile = user.profile
    user.is_active = True
    user.save(update_fields=['is_active'])
    profile.user_type = 'alumni'
    profile.class_level = None
    profile.graduation_year = registration.graduation_year
    profile.account_status = 'active'
    if not profile.github_username:
        profile.github_username = _canonical_social_value(alumni.github_url, 'github')
    if not profile.linkedin_slug:
        profile.linkedin_slug = _canonical_social_value(alumni.linkedin_url, 'linkedin')
    profile.save()
    registration.status = status
    registration.matched_alumni = alumni
    registration.reviewed_by = reviewer
    registration.reviewed_at = timezone.now()
    registration.rejection_reason = ''
    registration.moderation_description = ''
    registration.save()
    create_notification(
        recipient=user, actor=reviewer, notification_type='alumni_registration',
        title='Mezun hesabınız onaylandı',
        message='Mezun hesabınız etkinleştirildi. Artık giriş yapabilirsiniz.',
        target_url=reverse('accounts:login'), dedupe_key=f'alumni-approved:{registration.pk}', force=True,
    )
    _queue_registration_email(
        'BST Akademi - Mezun hesabınız onaylandı',
        'Mezun hesabınız onaylandı ve etkinleştirildi. Artık BST Portal hesabınıza giriş yapabilirsiniz.',
        user.email,
    )
    record_audit_event(
        actor=reviewer, action='alumni.registration_approved', target=registration, request=request,
        metadata={'alumni_id': alumni.pk, 'user_id': user.pk, 'approval_type': status},
    )
    return alumni


@transaction.atomic
def approve_existing_registration(*, registration_id, alumni_id, reviewer, request=None):
    if not can_review_alumni_registration(reviewer):
        raise PermissionDenied
    registration = AlumniRegistrationRequest.objects.select_for_update().select_related('user__profile').get(
        pk=registration_id
    )
    alumni = Alumni.objects.select_for_update().get(pk=alumni_id)
    if registration.status != 'pending':
        raise ValidationError('Bu mezun kayıt talebi daha önce sonuçlandırılmış.')
    if alumni.user_id and alumni.user_id != registration.user_id:
        raise ValidationError('Seçilen mezun kaydı başka bir hesaba bağlı.')
    if Alumni.objects.filter(user=registration.user).exclude(pk=alumni.pk).exists():
        raise ValidationError('Bu kullanıcı başka bir mezun kaydına bağlı.')
    alumni.user = registration.user
    if not alumni.student_number and registration.student_number:
        alumni.student_number = registration.student_number
    alumni.save()
    return _activate_request(registration, reviewer, alumni, 'approved_linked', request)


@transaction.atomic
def approve_new_registration(*, registration_id, reviewer, confirmed=False, request=None):
    if not can_review_alumni_registration(reviewer):
        raise PermissionDenied
    if not confirmed:
        raise ValidationError('Yeni mezun oluşturma için ikinci onay zorunludur.')
    registration = AlumniRegistrationRequest.objects.select_for_update().select_related('user__profile').get(
        pk=registration_id
    )
    if registration.status != 'pending':
        raise ValidationError('Bu mezun kayıt talebi daha önce sonuçlandırılmış.')
    if Alumni.objects.filter(user=registration.user).exists():
        raise ValidationError('Bu kullanıcı zaten bir mezun kaydına bağlı.')
    alumni = Alumni.objects.create(
        user=registration.user, full_name=registration.full_name,
        graduation_year=registration.graduation_year,
        student_number=registration.student_number or None,
    )
    return _activate_request(registration, reviewer, alumni, 'approved_new', request)


@transaction.atomic
def reject_registration(*, registration_id, reviewer, reason, description, request=None):
    if not can_review_alumni_registration(reviewer):
        raise PermissionDenied
    if reason not in {value for value, _ in MODERATION_REASON_CHOICES} or not description.strip():
        raise ValidationError('Standart red nedeni ve açıklama zorunludur.')
    registration = AlumniRegistrationRequest.objects.select_for_update().select_related('user').get(pk=registration_id)
    if registration.status != 'pending':
        raise ValidationError('Bu mezun kayıt talebi daha önce sonuçlandırılmış.')
    registration.status = 'rejected'
    registration.rejection_reason = reason
    registration.moderation_description = description.strip()
    registration.reviewed_by = reviewer
    registration.reviewed_at = timezone.now()
    registration.save()
    registration.user.is_active = False
    registration.user.save(update_fields=['is_active'])
    profile = registration.user.profile
    profile.account_status = 'closed'
    profile.suspension_reason = description.strip()
    profile.save(update_fields=['account_status', 'suspension_reason'])
    create_notification(
        recipient=registration.user, actor=reviewer, notification_type='alumni_registration',
        title='Mezun kayıt talebiniz sonuçlandı', message=f'Talebiniz reddedildi: {description.strip()}',
        dedupe_key=f'alumni-rejected:{registration.pk}', force=True,
    )
    _queue_registration_email(
        'BST Akademi - Mezun kayıt talebiniz sonuçlandı',
        f'Mezun kayıt talebiniz reddedildi. Açıklama: {description.strip()}',
        registration.email,
    )
    record_audit_event(
        actor=reviewer, action='alumni.registration_rejected', target=registration, request=request,
        metadata={'reason': reason, 'description': description.strip()},
    )
    return registration


@transaction.atomic
def unlink_alumni_account(*, alumni_id, reviewer, description, request=None):
    if not is_admin(reviewer):
        raise PermissionDenied
    if not description.strip():
        raise ValidationError('Bağlantıyı geri alma açıklaması zorunludur.')
    alumni = Alumni.objects.select_for_update().get(pk=alumni_id)
    previous_user_id = alumni.user_id
    alumni.user = None
    alumni.save(update_fields=['user'])
    record_audit_event(
        actor=reviewer, action='alumni.account_unlinked', target=alumni, request=request,
        metadata={'previous_user_id': previous_user_id, 'new_user_id': None, 'description': description.strip()},
    )
    return alumni
