"""Shared view decorators for DockLabs products.

Provides role-based access control decorators that work with any product's
User model that has a ``role`` field.

Usage:
    from keel.core.decorators import role_required

    @role_required('admin', 'program_officer')
    def my_view(request):
        ...

    @admin_required
    def admin_only_view(request):
        ...
"""
from functools import wraps

from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Restrict a view to users with one of the specified roles.

    Superusers always pass. Unauthenticated users are redirected to login.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            if request.user.is_superuser or getattr(request.user, 'role', None) in roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return _wrapped
    return decorator


def admin_required(view_func):
    """Shortcut: restrict to admin role."""
    return role_required('admin', 'system_admin')(view_func)


def staff_required(view_func):
    """Shortcut: restrict to admin or staff-level roles.

    Products define what "staff" means — this covers the most common
    role names across DockLabs products.
    """
    return role_required(
        'admin', 'system_admin', 'agency_admin',
        'legislative_aid', 'program_officer',
    )(view_func)
