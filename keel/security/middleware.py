"""
Keel Security Middleware — shared across all DockLabs products.

Provides:
- SecurityHeadersMiddleware: CSP (with per-request nonce), Permissions-Policy, and other security headers
- FailedLoginMonitor: Detects brute-force login attempts
- AdminIPAllowlistMiddleware: Restricts /admin/ access by IP

Usage in settings.py:
    MIDDLEWARE = [
        'django.middleware.security.SecurityMiddleware',
        'keel.security.middleware.SecurityHeadersMiddleware',
        'keel.security.middleware.FailedLoginMonitor',
        ...
    ]

    # Optional: restrict admin panel to specific IPs
    KEEL_ADMIN_ALLOWED_IPS = ['10.0.0.0/8', '192.168.0.0/16']

    # Optional: lockout after N failed logins (default 10 in 15 min)
    KEEL_LOGIN_MAX_FAILURES = 10
    KEEL_LOGIN_LOCKOUT_WINDOW = 900  # seconds
    KEEL_LOGIN_LOCKOUT_DURATION = 1800  # seconds

    # KEEL_CSP_POLICY may include the literal ``{nonce}`` placeholder, which
    # SecurityHeadersMiddleware substitutes per request. Pair with
    # ``keel.core.context_processors.csp_nonce_context`` so templates can
    # read ``{{ csp_nonce }}``. Example policy:
    #
    #     KEEL_CSP_POLICY = (
    #         "default-src 'self'; "
    #         "script-src 'self' 'nonce-{nonce}' 'unsafe-inline' https://cdn.jsdelivr.net; "
    #         "style-src  'self' 'nonce-{nonce}' 'unsafe-inline' https://cdn.jsdelivr.net; "
    #         ...
    #     )
    #
    # Keep ``'unsafe-inline'`` while migrating templates; once every inline
    # ``<script>`` / ``<style>`` carries ``nonce="{{ csp_nonce }}"``, drop
    # ``'unsafe-inline'`` from the policy to actually enforce strict-dynamic.
"""
import ipaddress
import logging
import secrets
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseForbidden

logger = logging.getLogger('keel.security')


def get_client_ip(request):
    """Return the real client IP, honoring X-Forwarded-For only when trusted.

    Django sees ``REMOTE_ADDR`` as the last hop — on Railway, that's Railway's
    own proxy. Clients can forge ``X-Forwarded-For`` on arbitrary requests, so
    trusting the leftmost hop unconditionally lets any attacker spoof their IP
    (and evade per-IP rate limits / admin allowlists).

    ``KEEL_TRUSTED_PROXY_COUNT`` declares how many trusted proxies sit in
    front of Django. For each one, we pop the rightmost hop of the
    ``X-Forwarded-For`` chain (the hop added by that proxy). Whatever is left
    at the tail is the real client. Default = 0 → ignore the header entirely
    and use ``REMOTE_ADDR``.
    """
    trusted = int(getattr(settings, 'KEEL_TRUSTED_PROXY_COUNT', 0) or 0)
    if trusted > 0:
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        hops = [h.strip() for h in forwarded_for.split(',') if h.strip()]
        # Pop `trusted` proxies from the right; the next rightmost hop is the
        # real client (the one *trusted[0]* saw).
        idx = len(hops) - trusted
        if idx >= 0 and idx < len(hops):
            return hops[idx]
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


# Back-compat alias — older imports may still use the leading-underscore form.
_get_client_ip = get_client_ip


def generate_csp_nonce():
    """Return a fresh, URL-safe nonce suitable for CSP3 ``'nonce-X'``.

    16 bytes → 22 base64url chars. Per CSP3 spec the nonce must be at
    least 128 bits of unguessable entropy.
    """
    return secrets.token_urlsafe(16)


class SecurityHeadersMiddleware:
    """Adds security headers beyond what Django's SecurityMiddleware provides.

    Per-request CSP nonce: stamps ``request.csp_nonce`` BEFORE the view runs
    so templates / context processors can read it, then substitutes any
    ``{nonce}`` placeholder in ``KEEL_CSP_POLICY`` with that value when
    setting the Content-Security-Policy header. If the policy doesn't
    contain ``{nonce}``, the nonce is still attached to the request for any
    callers that need it but the policy ships unchanged.

    **Nonce enforcement is opt-in per product** via
    ``KEEL_CSP_NONCE_ENABLED = True``. The Wave 4 rollout shipped the
    ``'nonce-{nonce}'`` token in every product's KEEL_CSP_POLICY alongside
    ``'unsafe-inline'`` as a transitional fallback — but per the CSP3 spec
    browsers IGNORE ``'unsafe-inline'`` the moment any ``'nonce-X'`` token
    appears in the same directive. With templates not yet tagged
    (task #39), this silently blocked every inline ``<script>`` and
    ``<style>`` across the suite — Bootstrap dropdowns, tooltips,
    inline status-pill styles, htmx handlers — 100+ CSP violations per
    page load, a fleet-wide UX regression masked by 200s on /health/.
    The default is now OFF: the middleware strips the entire
    ``'nonce-{nonce}'`` token from each directive so ``'unsafe-inline'``
    actually works. Products that have tagged every inline tag with
    ``nonce="{{ csp_nonce }}"`` opt in by setting
    ``KEEL_CSP_NONCE_ENABLED = True``, AND also dropping ``'unsafe-inline'``
    from their policy at the same time.
    """

    # Match ``'nonce-{nonce}'`` (with optional surrounding whitespace) so we
    # can excise the token without disturbing the rest of the directive.
    # Defined at class level so the regex compiles once per process.
    _NONCE_TOKEN_RE = None  # populated lazily in __call__

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Stamp the nonce on the request before the view runs so context
        # processors and templates can resolve {{ csp_nonce }} from the
        # request object. Use a fresh nonce per request.
        request.csp_nonce = generate_csp_nonce()

        response = self.get_response(request)

        # Content Security Policy — restrictive default, products can override
        if not response.has_header('Content-Security-Policy'):
            csp = getattr(settings, 'KEEL_CSP_POLICY', None)
            if csp:
                if '{nonce}' in csp:
                    if getattr(settings, 'KEEL_CSP_NONCE_ENABLED', False):
                        # Product has opted in: every inline <script>/<style>
                        # carries nonce="{{ csp_nonce }}" and 'unsafe-inline'
                        # has been dropped from KEEL_CSP_POLICY.
                        csp = csp.replace('{nonce}', request.csp_nonce)
                    else:
                        # Default: excise the entire ``'nonce-{nonce}'`` token
                        # from each directive so 'unsafe-inline' actually
                        # works. Inline ``re.sub`` keeps the patch contained.
                        import re
                        # Strip token along with any preceding whitespace.
                        csp = re.sub(r"\s*'nonce-\{nonce\}'", "", csp)
                        # Collapse any doubled whitespace left in the wake
                        # of the excision (e.g. ``script-src  'self'``).
                        csp = re.sub(r"  +", " ", csp).strip()
                response['Content-Security-Policy'] = csp

        # Permissions-Policy — disable dangerous browser features
        if not response.has_header('Permissions-Policy'):
            response['Permissions-Policy'] = (
                'camera=(), microphone=(), geolocation=(), '
                'payment=(), usb=(), magnetometer=(), gyroscope=()'
            )

        # Prevent MIME type confusion attacks
        response['X-Content-Type-Options'] = 'nosniff'

        # Prevent embedding in iframes (beyond X-Frame-Options)
        if not response.has_header('Cross-Origin-Opener-Policy'):
            response['Cross-Origin-Opener-Policy'] = 'same-origin'

        return response


class FailedLoginMonitor:
    """Detects and blocks brute-force login attempts.

    Tracks failed login attempts per IP. After KEEL_LOGIN_MAX_FAILURES
    failures within KEEL_LOGIN_LOCKOUT_WINDOW seconds, blocks the IP
    for KEEL_LOGIN_LOCKOUT_DURATION seconds.

    Also logs security events for monitoring.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.max_failures = getattr(settings, 'KEEL_LOGIN_MAX_FAILURES', 10)
        self.lockout_window = getattr(settings, 'KEEL_LOGIN_LOCKOUT_WINDOW', 900)
        self.lockout_duration = getattr(settings, 'KEEL_LOGIN_LOCKOUT_DURATION', 1800)
        self.login_paths = getattr(settings, 'KEEL_LOGIN_PATHS', [
            '/auth/login/', '/accounts/login/', '/admin/login/',
        ])

    def __call__(self, request):
        ip = get_client_ip(request)

        # Check if IP is currently locked out
        if self._is_locked_out(ip):
            logger.warning(
                'Blocked login attempt from locked-out IP: %s', ip,
                extra={'ip': ip, 'security_event': 'login_lockout_blocked'},
            )
            return HttpResponseForbidden(
                'Too many failed login attempts. Please try again later.',
                content_type='text/plain',
            )

        response = self.get_response(request)

        # Track failed login attempts (POST to login URL returning non-redirect)
        if (
            request.method == 'POST'
            and any(request.path.startswith(p) for p in self.login_paths)
            and response.status_code != 302
        ):
            self._record_failure(ip)

        # Clear failures on successful login
        if (
            request.method == 'POST'
            and any(request.path.startswith(p) for p in self.login_paths)
            and response.status_code == 302
        ):
            self._clear_failures(ip)

        return response

    def _cache_key(self, ip):
        return f'keel:login_failures:{ip}'

    def _lockout_key(self, ip):
        return f'keel:login_lockout:{ip}'

    def _is_locked_out(self, ip):
        return cache.get(self._lockout_key(ip)) is not None

    def _record_failure(self, ip):
        key = self._cache_key(ip)
        failures = cache.get(key, [])
        now = time.time()
        # Prune old failures outside the window
        failures = [t for t in failures if now - t < self.lockout_window]
        failures.append(now)
        cache.set(key, failures, timeout=self.lockout_window)

        # Approach D (v0.46.0): emit one Activity row per failed login so
        # /ops/ and security alerts have a queryable signal. AuditLog used
        # to carry these rows with user_id=NULL; under D the schema rejects
        # NULL-user audit writes, so the event lives in Activity instead.
        # Best-effort — never let an emission failure block the request.
        try:
            from keel.activity.services import record_system_event
            record_system_event(
                verb='auth.login_failed',
                summary=f'Login attempt failed from {ip}',
                status='warn',
                metadata={
                    'ip': ip,
                    'failures_in_window': len(failures),
                    'window_seconds': self.lockout_window,
                },
            )
        except Exception:
            logger.exception(
                'Failed to record auth.login_failed activity for ip=%s', ip,
            )

        if len(failures) >= self.max_failures:
            cache.set(self._lockout_key(ip), True, timeout=self.lockout_duration)
            logger.critical(
                'IP %s locked out after %d failed login attempts in %d seconds',
                ip, len(failures), self.lockout_window,
                extra={
                    'ip': ip,
                    'failures': len(failures),
                    'security_event': 'login_lockout',
                },
            )
            # Companion Activity row for the lockout itself. ``status='failed'``
            # so the routine notification pipeline fans this out to product
            # system_admins through the Activity → Notification seam.
            try:
                from keel.activity.services import record_system_event
                record_system_event(
                    verb='security.account_locked',
                    summary=f'IP {ip} locked out after {len(failures)} '
                            f'failed attempts in {self.lockout_window}s',
                    status='failed',
                    metadata={
                        'ip': ip,
                        'failures': len(failures),
                        'window_seconds': self.lockout_window,
                        'lockout_seconds': self.lockout_duration,
                    },
                )
            except Exception:
                logger.exception(
                    'Failed to record security.account_locked activity '
                    'for ip=%s', ip,
                )

    def _clear_failures(self, ip):
        cache.delete(self._cache_key(ip))


class AdminIPAllowlistMiddleware:
    """Restricts /admin/ access to a list of allowed IP addresses/networks.

    Wiring (required — this middleware is NOT enabled by default):
        Add to MIDDLEWARE in each product's settings.py, AFTER
        SecurityHeadersMiddleware and BEFORE AuthenticationMiddleware so the
        403 is returned before any auth work happens:

            MIDDLEWARE = [
                ...
                'keel.security.middleware.SecurityHeadersMiddleware',
                'keel.security.middleware.AdminIPAllowlistMiddleware',
                ...
                'django.contrib.auth.middleware.AuthenticationMiddleware',
                ...
            ]

    Configure in settings:
        KEEL_ADMIN_ALLOWED_IPS = ['10.0.0.0/8', '192.168.0.0/16', '1.2.3.4']
        KEEL_ADMIN_URL_PREFIX = '/admin/'  # optional, defaults to '/admin/'

    Behavior: if KEEL_ADMIN_ALLOWED_IPS is unset or empty, the middleware is
    a no-op (all IPs allowed). This keeps local dev working without extra
    config but means production MUST populate the list to get protection.
    Pull the client IP from a trusted proxy header — see get_client_ip.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        raw = getattr(settings, 'KEEL_ADMIN_ALLOWED_IPS', [])
        self.networks = []
        for entry in raw:
            try:
                self.networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                logger.warning('Invalid IP/network in KEEL_ADMIN_ALLOWED_IPS: %s', entry)

    def __call__(self, request):
        admin_prefix = getattr(settings, 'KEEL_ADMIN_URL_PREFIX', '/admin/')
        if self.networks and request.path.startswith(admin_prefix):
            ip = get_client_ip(request)
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                return HttpResponseForbidden('Access denied.', content_type='text/plain')

            if not any(addr in net for net in self.networks):
                logger.warning(
                    'Admin access denied for IP %s to %s',
                    ip, request.path,
                    extra={'ip': ip, 'security_event': 'admin_access_denied'},
                )
                # Activity row so /ops/ surfaces the denied access (Approach D).
                try:
                    from keel.activity.services import record_system_event
                    record_system_event(
                        verb='security.suspicious_activity',
                        summary=f'Admin access denied for IP {ip}',
                        status='warn',
                        metadata={
                            'ip': ip,
                            'path': request.path,
                            'event_type': 'admin_access_denied',
                        },
                    )
                except Exception:
                    logger.exception(
                        'Failed to record security.suspicious_activity '
                        'activity for ip=%s', ip,
                    )
                return HttpResponseForbidden('Access denied.', content_type='text/plain')

        return self.get_response(request)
