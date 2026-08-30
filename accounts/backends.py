from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User

class EmailBackend(ModelBackend):
    def authenticate(self, request, email=None, password=None, **kwargs):
        if not email or not password:
            return None
        user = User.objects.filter(email__iexact=email.strip()).order_by('-date_joined').first()
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        """Prevent inactive users from logging in"""
        is_active = getattr(user, 'is_active', None)
        return is_active is None or is_active
