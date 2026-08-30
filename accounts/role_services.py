from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse

from core.audit import record_audit_event
from core.notifications import create_notification

from .policies import is_admin


ASSIGNABLE_STUDENT_ROLES = {
    'student': 'Öğrenci',
    'staff_student': 'BST Yetkilisi',
}


@transaction.atomic
def change_student_authority_role(*, actor, target, new_role, description, request=None):
    """Safely switch an ordinary student account to/from BST authority."""

    if not is_admin(actor) or actor.pk == target.pk:
        raise PermissionDenied('Bu hesabın rolünü değiştirme yetkiniz yok.')

    locked_target = (
        type(target).objects.select_for_update()
        .select_related('profile')
        .get(pk=target.pk)
    )
    profile = locked_target.profile
    previous_role = profile.user_type
    description = (description or '').strip()

    if locked_target.is_staff or locked_target.is_superuser:
        raise PermissionDenied('Yönetici hesaplarının rolü bu ekrandan değiştirilemez.')
    if previous_role not in ASSIGNABLE_STUDENT_ROLES:
        raise ValidationError('Yalnızca öğrenci ve BST Yetkilisi hesapları arasında rol değişimi yapılabilir.')
    if new_role not in ASSIGNABLE_STUDENT_ROLES:
        raise ValidationError('Seçilen rol bu işlem için kullanılamaz.')
    if previous_role == new_role:
        raise ValidationError('Kullanıcının rolü zaten seçtiğiniz rolle aynı.')
    if not description:
        raise ValidationError('Rol değişikliği açıklaması zorunludur.')

    profile.user_type = new_role
    profile.save(update_fields=['user_type', 'updated_at'])

    record_audit_event(
        actor=actor,
        action='user.role_changed',
        target=locked_target,
        request=request,
        metadata={
            'previous_role': previous_role,
            'new_role': new_role,
            'previous_role_label': ASSIGNABLE_STUDENT_ROLES[previous_role],
            'new_role_label': ASSIGNABLE_STUDENT_ROLES[new_role],
            'description': description,
        },
    )
    create_notification(
        recipient=locked_target,
        actor=actor,
        notification_type='moderation',
        title='Hesap rolünüz güncellendi',
        message=(
            f'Hesap rolünüz {ASSIGNABLE_STUDENT_ROLES[previous_role]} rolünden '
            f'{ASSIGNABLE_STUDENT_ROLES[new_role]} rolüne değiştirildi.'
        ),
        target_url=reverse('accounts:portfolio_settings'),
        dedupe_key='',
        force=True,
    )
    return locked_target
