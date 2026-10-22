"""
Custom authentication backend.

Allows a User (member) to log in with ANY of:
    - email
    - library card ID
    - phone number
along with their password. Inactive accounts (is_active=False) are
always rejected, matching the requirement that deactivated
users/librarians cannot log in.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class MultiFieldAuthBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get('identifier')
        if identifier is None or password is None:
            return None

        try:
            user = User.objects.get(
                Q(email__iexact=identifier)
                | Q(library_card_id__iexact=identifier)
                | Q(phone_number=identifier)
                | Q(username__iexact=identifier)
            )
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
