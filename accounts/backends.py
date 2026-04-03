from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User

class EmailBackend(ModelBackend):
    def authenticate(self, request, email=None, password=None, **kwargs):
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return None
        if user.check_password(password):
            return user
        return None

    def user_can_authenticate(self, user):
        """Prevent inactive users from logging in"""
        is_active = getattr(user, 'is_active', None)
        return is_active is None or is_active