from django.core.exceptions import PermissionDenied


def ensure_interactive_account(user):
    profile = getattr(user, 'profile', None)
    if not user.is_authenticated or not user.is_active or not profile or profile.account_status != 'active':
        raise PermissionDenied('Bu işlem için aktif ve doğrulanmış bir hesap gereklidir.')
    return True


def can_share_content(user):
    profile = getattr(user, 'profile', None)
    return bool(
        user.is_authenticated
        and user.is_active
        and profile
        and profile.account_status == 'active'
        and profile.user_type != 'visitor'
    )


def ensure_full_participation_account(user):
    ensure_interactive_account(user)
    if getattr(user.profile, 'user_type', '') == 'visitor':
        raise PermissionDenied('Ziyaretçi hesapları bu işlemi yapamaz. İçerik paylaşmak için Onaylı Üye onayı gerekir.')
    return True
