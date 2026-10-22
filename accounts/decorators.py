"""
Server-side role-checking decorators.

IMPORTANT: These checks run on the server for every request, so a user
cannot bypass them just by typing a URL directly into the browser.
Anyone without the right role gets a clean 403 Forbidden page instead
of the protected content.
"""
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser or user.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to view this page.")
        return _wrapped
    return decorator


admin_required = role_required('ADMIN')
librarian_required = role_required('ADMIN', 'LIBRARIAN')
user_required = role_required('USER')
staff_required = role_required('ADMIN', 'LIBRARIAN')
