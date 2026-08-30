from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.db import OperationalError, ProgrammingError


BST_AUTHORITY_GROUP = 'BST Yetkilisi'
SAFE_PROFILE_PERMISSIONS = {
    'moderate_accounts',
    'review_profile_websites',
    'review_user_reports',
    'review_alumni_registrations',
    'review_project_requests',
    'review_collaborations',
    'review_contributor_applications',
}


def bootstrap_bst_authority_group():
    group, _ = Group.objects.get_or_create(name=BST_AUTHORITY_GROUP)
    permissions = Permission.objects.filter(
        Q(content_type__app_label='accounts', codename__in=SAFE_PROFILE_PERMISSIONS)
        | Q(
            content_type__app_label='news',
            codename__in={'add_article', 'change_article', 'delete_article', 'view_article'},
        )
        | Q(
            content_type__app_label='events',
            codename__in={'add_event', 'change_event', 'delete_event', 'view_event'},
        )
    )
    group.permissions.set(permissions)
    from .models import Profile
    authorities = Profile.objects.filter(
        user_type='staff_student',
        user__is_staff=False,
        user__is_superuser=False,
    ).select_related('user')
    for profile in authorities:
        profile.user.groups.add(group)
    legacy_admins = Profile.objects.filter(user_type='staff_student').filter(
        Q(user__is_staff=True) | Q(user__is_superuser=True)
    ).select_related('user')
    for profile in legacy_admins:
        profile.user.groups.remove(group)
    return group


def sync_user_authority_group(user, user_type):
    try:
        group = Group.objects.filter(name=BST_AUTHORITY_GROUP).first()
        if group is None:
            return
        if user_type == 'staff_student' and not user.is_staff and not user.is_superuser:
            user.groups.add(group)
        else:
            user.groups.remove(group)
    except (OperationalError, ProgrammingError):
        return
