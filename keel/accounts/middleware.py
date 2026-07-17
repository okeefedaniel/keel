"""Keel accounts middleware — product role resolution and access gating.

Usage in product settings.py:

    MIDDLEWARE = [
        ...
        'keel.accounts.middleware.AutoOIDCLoginMiddleware',  # before auth
        'keel.accounts.middleware.ProductAccessMiddleware',
        'keel.accounts.middleware.SessionFreshnessMiddleware',  # after auth
        ...
    ]

    KEEL_PRODUCT_CODE = 'harbor'  # must match ProductAccess.product value
"""
import base64
import logging
import os
from datetime import datetime
from urllib.parse import quote, urlencode

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

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
        from keel.core.utils import get_product_code
        self.product = get_product_code()
        self.gate_access = getattr(settings, 'KEEL_GATE_ACCESS', False)
        self.exempt_paths = tuple(
            getattr(settings, 'KEEL_EXEMPT_PATHS', DEFAULT_EXEMPT_PATHS)
        )

    def __call__(self, request):
        user = getattr(request, 'user', None)

        # Expose organization claims on every request so views can read
        # ``request.organization_slug`` / ``request.organization_name``
        # without re-parsing the session. Defaults to None for
        # unauthenticated requests, OIDC sessions without the
        # 'organization' scope, and cross-org superusers.
        request.organization_slug = None
        request.organization_name = None

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
                # Organization claims (post-Layer-2 rollout). Read-only
                # passthrough — products may use this for analytics,
                # filtering, or display, but enforcement of subscription
                # gating lives at the Keel boundary, not here.
                org_slug = claims.get('organization')
                if org_slug:
                    request.organization_slug = org_slug
                org_name = claims.get('organization_name')
                if org_name:
                    request.organization_name = org_name

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
        # Read from Django settings first; fall back to env var so the
        # toggle works without forcing every consumer's settings.py to
        # add an explicit `KEEL_DEMO_FORCE_OIDC = os.environ.get(...)`
        # line. This is a deployment-time toggle, not a code-level one.
        self.demo_force_oidc = bool(
            getattr(settings, 'KEEL_DEMO_FORCE_OIDC', False)
            or os.environ.get('KEEL_DEMO_FORCE_OIDC', '').lower()
            in ('true', '1', 'yes')
        )

    def __call__(self, request):
        # Demo instances deliberately don't auto-bounce through OIDC by
        # default — they're supposed to have only the one-click demo role
        # users, and auto-starting SSO would lay a real DockLabs identity
        # row in the demo DB. Set KEEL_DEMO_FORCE_OIDC=True on a demo
        # instance that IS supposed to act as a real OIDC client (e.g. a
        # cross-suite demo where demo-keel is the IdP and the fleet
        # walkthrough should SSO across products without re-login).
        demo_skip = (
            getattr(settings, 'DEMO_MODE', False)
            and not self.demo_force_oidc
        )
        if (
            self.client_id
            and request.method in ('GET', 'HEAD')
            and request.path in _LOGIN_PATHS
            and 'next' in request.GET
            and not demo_skip
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
                # Guard against reflected open-redirect / phishing pivot:
                # only accept same-origin paths. Protocol-relative
                # ("//evil.com/...") and absolute URLs are rejected.
                if not next_url.startswith('/') or next_url.startswith('//'):
                    next_url = '/dashboard/'
                params = urlencode({'process': 'login', 'next': next_url})
                return HttpResponseRedirect(f'{login_path}?{params}')
        return self.get_response(request)


# ---------------------------------------------------------------------------
# Suite-wide logout propagation (Phase 2c)
# ---------------------------------------------------------------------------

#: Cache TTL for the per-user last_logout_at lookup. Bounds the worst-case
#: staleness — a user who signs out at Keel will be evicted from a peer
#: product's session within at most this many seconds. Keep it short
#: enough that the security/UX win is real, long enough that we don't
#: flood Keel with one HTTP call per page request.
SESSION_FRESHNESS_CACHE_TTL = 60

#: Failure-mode cache TTL. When Keel is unreachable or returns an error
#: we still cache the result (as ``None``) for a shorter window so we
#: don't hammer Keel during an outage but also don't leave users
#: indefinitely stuck on a stale session if Keel comes back.
SESSION_FRESHNESS_FAILURE_TTL = 30


class SessionFreshnessMiddleware:
    """Invalidate stale per-product sessions when the user logs out at Keel.

    Each product maintains its own Django session cookie scoped to its
    own subdomain. Without this middleware, signing out at Keel (or at
    any other product, which chains through Keel via SuiteLogoutView)
    has no effect on the per-product sessions held by peer products —
    the user remains "logged in" everywhere except the product they
    actually signed out of, until each session cookie organically
    expires (30 days by default).

    This middleware closes that gap by polling Keel's
    ``/oauth/session-status/?sub=<sub>`` on each authenticated request
    (cached per-user for ``SESSION_FRESHNESS_CACHE_TTL`` seconds) and
    comparing the returned ``last_logout_at`` against the
    ``keel_oidc_login_at`` timestamp stamped into the session at
    OIDC-login time by ``KeelSocialAccountAdapter.pre_social_login``.
    If Keel's logout is newer, the local session is torn down and the
    user is bounced to login.

    No-ops when:
    - ``KEEL_OIDC_CLIENT_ID`` is unset (standalone deployment)
    - ``DEMO_MODE`` is True
    - the user is not authenticated
    - the session has no ``keel_oidc_login_at`` (legacy session,
      pre-middleware sign-in, or local-form login)
    - the request path matches an exempt prefix (static, admin, etc.)

    Fails open: a Keel-side outage logs a warning but does not lock
    users out of products. Worst case we propagate logouts a little
    slowly while Keel is down.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.client_id = getattr(settings, 'KEEL_OIDC_CLIENT_ID', '')
        self.client_secret = getattr(settings, 'KEEL_OIDC_CLIENT_SECRET', '')
        issuer = getattr(settings, 'KEEL_OIDC_ISSUER', '') or ''
        # KEEL_SESSION_STATUS_URL lets a deployment override the lookup
        # endpoint (useful in tests). Default derives it from the issuer
        # so no per-product configuration is needed.
        self.status_url = (
            getattr(settings, 'KEEL_SESSION_STATUS_URL', '')
            or (f'{issuer.rstrip("/")}/oauth/session-status/' if issuer else '')
        )
        self.exempt_paths = tuple(
            getattr(settings, 'KEEL_EXEMPT_PATHS', DEFAULT_EXEMPT_PATHS)
        )
        # Effective only when we have everything we need to call Keel.
        # Demo instances normally skip session-freshness polling; setting
        # KEEL_DEMO_FORCE_OIDC=True opts them back in so a cross-suite
        # demo's logout chain behaves like prod. Same env-var fallback
        # as AutoOIDCLoginMiddleware (above) so the toggle works without
        # touching each product's settings.py.
        force = bool(
            getattr(settings, 'KEEL_DEMO_FORCE_OIDC', False)
            or os.environ.get('KEEL_DEMO_FORCE_OIDC', '').lower()
            in ('true', '1', 'yes')
        )
        demo_skip = getattr(settings, 'DEMO_MODE', False) and not force
        self.enabled = bool(
            self.client_id
            and self.client_secret
            and self.status_url
            and not demo_skip
        )

    def __call__(self, request):
        if not self.enabled:
            return self.get_response(request)
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return self.get_response(request)
        if any(request.path.startswith(p) for p in self.exempt_paths):
            return self.get_response(request)
        session = getattr(request, 'session', None)
        if session is None:
            return self.get_response(request)
        login_at_raw = session.get('keel_oidc_login_at')
        claims = session.get('keel_oidc_claims') or {}
        sub = (claims.get('sub') or '').strip() if isinstance(claims, dict) else ''
        if not login_at_raw or not sub:
            # Pre-Phase-2c session, or a non-OIDC login (local form,
            # direct Microsoft SSO). Nothing to compare against.
            return self.get_response(request)

        last_logout_at = self._fetch_last_logout(sub)
        if last_logout_at is None:
            return self.get_response(request)

        login_at = _parse_iso(login_at_raw)
        if login_at is None:
            return self.get_response(request)

        if last_logout_at > login_at:
            logger.info(
                'SessionFreshness: tearing down stale session for %s '
                '(login_at=%s, keel_logout_at=%s)',
                user, login_at.isoformat(), last_logout_at.isoformat(),
            )
            auth_logout(request)
            # Bounce to login so AutoOIDCLoginMiddleware (or the local
            # form, on standalone) can re-authenticate. Preserve where
            # the user was trying to go so they land back there after
            # signing back in.
            login_url = getattr(settings, 'LOGIN_URL', None) or '/accounts/login/'
            params = urlencode({'next': request.get_full_path()})
            return HttpResponseRedirect(f'{login_url}?{params}')

        return self.get_response(request)

    # ------------------------------------------------------------------
    # Keel /oauth/session-status/ lookup, cached per sub
    # ------------------------------------------------------------------
    def _fetch_last_logout(self, sub):
        """Return Keel's ``last_logout_at`` for ``sub`` or ``None``.

        Cached for ``SESSION_FRESHNESS_CACHE_TTL`` seconds so the hot
        path is a single Redis/memcached hit per user per minute. A
        sentinel ``''`` is cached when Keel says ``null`` (user has
        never logged out at Keel), distinguished from a genuine cache
        miss (``None`` from ``cache.get``).
        """
        cache_key = f'keel:last_logout:{sub}'
        cached = cache.get(cache_key)
        if cached == '':
            return None
        if isinstance(cached, datetime):
            return cached
        # Cache miss — call Keel.
        try:
            value = self._call_keel(sub)
        except Exception:
            logger.warning(
                'SessionFreshness: Keel session-status lookup failed for sub=%s; '
                'failing open',
                sub, exc_info=True,
            )
            cache.set(cache_key, '', SESSION_FRESHNESS_FAILURE_TTL)
            return None
        if value is None:
            cache.set(cache_key, '', SESSION_FRESHNESS_CACHE_TTL)
            return None
        cache.set(cache_key, value, SESSION_FRESHNESS_CACHE_TTL)
        return value

    def _call_keel(self, sub):
        # Lazy import: requests is already a transitive dep via allauth,
        # but keep the import out of module load so import-time errors
        # in test envs without it produce useful tracebacks.
        import requests

        creds = f'{self.client_id}:{self.client_secret}'.encode('utf-8')
        auth_header = 'Basic ' + base64.b64encode(creds).decode('ascii')
        response = requests.get(
            self.status_url,
            params={'sub': sub},
            headers={'Authorization': auth_header},
            timeout=2.0,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f'Keel session-status returned HTTP {response.status_code}'
            )
        payload = response.json()
        raw = payload.get('last_logout_at')
        if not raw:
            return None
        parsed = _parse_iso(raw)
        if parsed is None:
            raise RuntimeError(
                f'Keel session-status returned unparsable last_logout_at={raw!r}'
            )
        return parsed


class AIKeyClaimRefreshMiddleware:
    """Self-heal a stale ``ai_key_present`` OIDC claim mid-session.

    ``ai_key_present`` is a login-time snapshot in the user's
    ``SocialAccount.extra_data`` (see ``keel.core.sso``). If a user sets
    their Anthropic key on Keel *after* logging into this product, the
    snapshot stays ``False`` until their next full OIDC login, so the AI
    gate keeps showing the "you have not yet put in your API key" prompt
    and keeps AI features disabled even though the key exists. Users read
    that as "I already added my key — why is it still asking?".

    This middleware re-checks the claim out-of-band — via the existing
    security-hardened cross-product key fetch (``keel.core.ai_key_refresh``
    → ``keel.core.ai._fetch_key_from_keel``) — and rewrites the snapshot
    when it has gone stale. It is deliberately conservative:

    - **No-ops** unless authenticated, in suite mode, and past a
      per-session TTL gate (``AI_KEY_REFRESH_TTL``). The TTL check is the
      first thing that runs, so the overwhelming majority of requests exit
      in a dict lookup with zero queries.
    - **Only** does network work for users actually in the ``needs_key``
      state — i.e. exactly the users seeing the false prompt. A user who
      already has a key never triggers a check.
    - **Best-effort.** Any failure (Keel down, access token too stale to
      fetch, network error) leaves the stored claim untouched and never affects
      the response. It can only ever *correct* a stale ``False`` claim; it
      never makes the gate more permissive on error.

    Wire it after ``ProductAccessMiddleware`` (needs ``request.user`` and
    the session). Enabling it is opt-in per product via ``MIDDLEWARE``;
    products that don't add it keep the login-time-only behavior.
    """

    SESSION_KEY = '_ai_key_checked_at'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            self._maybe_refresh(request)
        except Exception:  # noqa: BLE001 — must never break the request
            logger.debug('AIKeyClaimRefreshMiddleware skipped', exc_info=True)
        return self.get_response(request)

    def _maybe_refresh(self, request):
        import time

        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return
        session = getattr(request, 'session', None)
        if session is None:
            return

        from keel.core.utils import is_suite_mode
        if not is_suite_mode():
            return

        from keel.core.ai_key_refresh import AI_KEY_REFRESH_TTL, refresh_ai_key_claim

        now = time.time()
        last = session.get(self.SESSION_KEY)
        if isinstance(last, (int, float)) and (now - last) < AI_KEY_REFRESH_TTL:
            return  # Cheap fast-path: checked recently, nothing to do.

        # Past the TTL gate — mark checked up front so a slow or failed
        # check doesn't re-fire on every subsequent request this window.
        session[self.SESSION_KEY] = now

        from keel.core.ai_access import user_ai_state
        if user_ai_state(user) != 'needs_key':
            return  # 'ready' (has key) or 'off' (no AI access) — nothing to fix.

        refresh_ai_key_claim(user)


def _parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware datetime, or None.

    Accepts both ``Z``-suffixed and explicit-offset forms. Naive values
    are coerced to the current Django timezone — sessions stamped before
    we standardized on aware-only timestamps may be missing tzinfo.
    """
    if not isinstance(value, str):
        return None
    raw = value.replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed
