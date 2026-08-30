from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse


class TemporaryPasswordChangeMiddleware:
    """Keep temporary-password users in the password-change flow until completion."""

    ALLOWED_VIEW_NAMES = {
        'accounts:portfolio_settings',
        'accounts:password_change',
        'accounts:logout',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        profile = getattr(user, 'profile', None) if user and user.is_authenticated else None
        if profile and profile.must_change_password:
            try:
                view_name = resolve(request.path_info).view_name
            except Resolver404:
                view_name = None
            if view_name not in self.ALLOWED_VIEW_NAMES:
                return redirect(reverse('accounts:portfolio_settings'))
        return self.get_response(request)
