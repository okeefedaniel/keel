"""Keel accounts middleware — product role resolution and access gating.

Usage in product settings.py:

    MIDDLEWARE = [
        ...
        'keel.accounts.middleware.AutoOIDCLoginMiddleware',  # before auth
        'keel.accounts.middleware.ProductAccessMiddleware',
        ...
    ]

    KEEL_PRODUCT_NAME = 'harbor'  # must match ProductAccess.product value
"""
import logging
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

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
            role = None

            # 1. Prefer JWT claim from session (set by allauth OIDC adapter
            #    after a successful Keel-IdP login). Phase 2b: this lets
            #    products skip the database lookup entirely when running
            #    against an OIDC issuer like Keel.
            claims = request.session.get('keel_oidc_claims') if hasattr(request, 'session') else None
            if claims and isinstance(claims, dict):
                product_access = claims.get('product_access') or {}
                if isinstance(product_access, dict):
                    role = product_access.get(self.product)

            # 2. Fall back to direct database lookup. This path keeps
            #    standalone deployments working (no Keel IdP) and is also
            #    the path used until Phase 2b OIDC migration is complete.
            if role is None:
                from keel.accounts.models import ProductAccess
                access = ProductAccess.objects.filter(
                    user=user,
                    product=self.product,
                    is_active=True,
                ).first()
                if access:
                    role = access.role

            user._product_role = role

            # Optionally block users who lack product access
            if role is None and self.gate_access and not user.is_superuser:
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


# Login URL paths used by various products. We auto-OIDC on these only.
_LOGIN_PATHS = ('/accounts/login/', '/auth/login/')


class AutoOIDCLoginMiddleware:
    """Auto-start the Keel OIDC flow when a user lands on the local login
    page after being bounced by ``@login_required``.

    This is the bridge between Django's ``LOGIN_URL`` redirect contract
    and the Keel suite SSO flow. Without it, clicking a product in the
    fleet switcher (e.g. Harbor) takes the user to that product's
    login page, where they have to click "Sign in with DockLabs"
    *manually* even though Keel already has an active session for them.

    With it, the flow becomes:

        click Harbor in fleet switcher
        → harbor.docklabs.ai/dashboard/
        → @login_required → 302 /accounts/login/?next=/dashboard/
        → AutoOIDCLoginMiddleware sees ?next= and KEEL_OIDC_CLIENT_ID set
        → 302 /accounts/oidc/keel/login/?process=login&next=/dashboard/
        → Keel sees its own session → immediately issues code
        → harbor receives code → local session created
        → harbor/dashboard/ ✓

    Direct visits to ``/accounts/login/`` (no ``?next=``) still render
    the form so users can sign in via the local form, the Microsoft
    button, or the DockLabs button if they prefer.

    Configuration: install in ``MIDDLEWARE`` somewhere after
    ``AuthenticationMiddleware`` and before ``ProductAccessMiddleware``.
    Active only when ``KEEL_OIDC_CLIENT_ID`` is set.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.client_id = getattr(settings, 'KEEL_OIDC_CLIENT_ID', '')

    def __call__(self, request):
        if (
            self.client_id
            and request.method in ('GET', 'HEAD')
            and request.path in _LOGIN_PATHS
            and 'next' in request.GET
        ):
            user = getattr(request, 'user', None)
            if user is None or not user.is_authenticated:
                # Resolve the OIDC login URL via reverse() so we pick up
                # whatever prefix the product mounts allauth under — most
                # products use /accounts/, but yeoman uses /auth/, and any
                # future product may differ. Hardcoding /accounts/ gave
                # yeoman a 404 loop on every @login_required bounce.
                try:
                    login_path = reverse(
                        'openid_connect_login',
                        kwargs={'provider_id': 'keel'},
                    )
                except NoReverseMatch:
                    return self.get_response(request)
                next_url = request.GET.get('next') or '/dashboard/'
                params = urlencode({'process': 'login', 'next': next_url})
                return HttpResponseRedirect(f'{login_path}?{params}')
        return self.get_response(request)
