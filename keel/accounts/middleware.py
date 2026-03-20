"""Keel accounts middleware — product role resolution and access gating.

Usage in product settings.py:

    MIDDLEWARE = [
        ...
        'keel.accounts.middleware.ProductAccessMiddleware',
        ...
    ]

    KEEL_PRODUCT_NAME = 'harbor'  # must match ProductAccess.product value
"""
import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

# Paths that should never be gated (login, static, admin, etc.)
DEFAULT_EXEMPT_PATHS = (
    '/accounts/', '/auth/', '/admin/', '/demo-login/',
    '/static/', '/media/', '/favicon', '/invite/',
)


class ProductAccessMiddleware:
    """Resolve the current user's role for this product on every request.

    Sets request.user._product_role so that KeelUser.role property
    and @role_required decorators work transparently.

    If KEEL_GATE_ACCESS is True (default False), unauthenticated
    product access is blocked — users without a ProductAccess record
    for this product get a 403.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.product = getattr(settings, 'KEEL_PRODUCT_NAME', '').lower()
        self.gate_access = getattr(settings, 'KEEL_GATE_ACCESS', False)
        self.exempt_paths = tuple(
            getattr(settings, 'KEEL_EXEMPT_PATHS', DEFAULT_EXEMPT_PATHS)
        )

    def __call__(self, request):
        user = getattr(request, 'user', None)

        if user and user.is_authenticated and self.product:
            # Look up this user's access for the current product
            from keel.accounts.models import ProductAccess
            access = ProductAccess.objects.filter(
                user=user,
                product=self.product,
                is_active=True,
            ).first()

            if access:
                user._product_role = access.role
            else:
                user._product_role = None

                # Optionally block users who lack product access
                if self.gate_access and not user.is_superuser:
                    if not self._is_exempt(request.path):
                        logger.warning(
                            'User %s denied access to %s (no ProductAccess)',
                            user, self.product,
                        )
                        raise PermissionDenied(
                            'You do not have access to this application.'
                        )

        return self.get_response(request)

    def _is_exempt(self, path):
        return any(path.startswith(prefix) for prefix in self.exempt_paths)
