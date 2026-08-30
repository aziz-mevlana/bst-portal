def user_type(request):
    """Add user_type to all templates"""
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        role = request.user.profile.user_type
        from accounts.policies import (
            can_access_management, can_manage_events, can_manage_news, is_admin,
        )
        from accounts.permissions import can_share_content
        management_access = can_access_management(request.user)
        admin_account = is_admin(request.user)
        if admin_account or role == 'teacher':
            panel_label = 'Yönetim Paneli'
        elif role == 'staff_student':
            panel_label = 'BST Yetkilisi Paneli'
        elif role == 'student':
            panel_label = 'Öğrenci Paneli'
        elif role == 'alumni':
            panel_label = 'Mezun Paneli'
        elif role == 'visitor':
            panel_label = None
        elif role == 'approved_member':
            panel_label = 'Onaylı Üye Paneli'
        else:
            panel_label = 'Panelim'
        return {
            'user_type': role,
            'can_access_management': management_access,
            'is_admin_account': admin_account,
            'is_bst_authority': role == 'staff_student' and not admin_account,
            'can_manage_news_content': can_manage_news(request.user),
            'can_manage_event_content': can_manage_events(request.user),
            'can_review_project_requests': (
                admin_account
                or role == 'teacher'
                or request.user.has_perm('accounts.review_project_requests')
            ),
            'can_moderate_accounts': request.user.has_perm('accounts.moderate_accounts'),
            'can_review_alumni_registrations': request.user.has_perm('accounts.review_alumni_registrations'),
            'can_review_profile_websites': request.user.has_perm('accounts.review_profile_websites'),
            'can_review_contributor_applications': request.user.has_perm('accounts.review_contributor_applications'),
            'can_share_content': can_share_content(request.user),
            'panel_label': panel_label,
            'show_dashboard_link': role != 'visitor',
        }
    return {
        'user_type': None,
        'can_access_management': False,
        'is_admin_account': False,
        'is_bst_authority': False,
        'can_manage_news_content': False,
        'can_manage_event_content': False,
        'can_review_project_requests': False,
        'can_moderate_accounts': False,
        'can_review_alumni_registrations': False,
        'can_review_profile_websites': False,
        'can_review_contributor_applications': False,
        'can_share_content': False,
        'panel_label': None,
        'show_dashboard_link': False,
    }
