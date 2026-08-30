"""Central authorization rules for dashboard and moderation operations."""


def is_admin(user):
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def role_of(user):
    profile = getattr(user, 'profile', None)
    return getattr(profile, 'user_type', '')


def is_teacher(user):
    return bool(user.is_authenticated and role_of(user) == 'teacher')


def is_bst_authority(user):
    return bool(
        user.is_authenticated
        and not is_admin(user)
        and role_of(user) == 'staff_student'
        and user.has_perm('accounts.moderate_accounts')
    )


def can_access_management(user):
    return is_admin(user) or is_teacher(user) or is_bst_authority(user)


def can_manage_news(user):
    return is_admin(user) or is_teacher(user) or user.has_perm('news.change_article')


def can_manage_events(user, action='view'):
    """Keep event permissions explicit for BST authorities.

    Academics and Django administrators retain their existing event workflow.
    A BST authority only receives the model permission assigned to the safe
    authority group; the role itself never turns the student into an admin.
    """

    if not user.is_authenticated:
        return False
    if is_admin(user) or is_teacher(user):
        return True
    if role_of(user) != 'staff_student':
        return False
    if action not in {'add', 'change', 'delete', 'view'}:
        return False
    return user.has_perm(f'events.{action}_event')


def can_review_website(user):
    return is_admin(user) or user.has_perm('accounts.review_profile_websites')


def can_review_alumni_registration(user):
    return is_admin(user) or user.has_perm('accounts.review_alumni_registrations')


def can_moderate_target(actor, target, action):
    if not actor.is_authenticated or actor.pk == target.pk:
        return False
    if is_admin(actor):
        return True
    if not is_bst_authority(actor):
        return False
    target_role = role_of(target)
    if target.is_staff or target.is_superuser or target_role in {'teacher', 'staff_student'}:
        return False
    if target_role not in {'student', 'alumni'}:
        return False
    allowed = {'suspend', 'reactivate', 'request_reverification', 'remove_photo'}
    if action == 'end_sessions':
        return actor.has_perm('accounts.end_user_sessions')
    return action in allowed
