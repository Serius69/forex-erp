# users/auth_backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate with email OR username + password."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        if '@' in username:
            try:
                user = User.objects.get(email=username.lower())
            except User.DoesNotExist:
                return None
        else:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
