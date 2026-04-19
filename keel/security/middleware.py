"""
Keel Security Middleware — shared across all DockLabs products.

Provides:
- SecurityHeadersMiddleware: CSP, Permissions-Policy, and other security headers
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
"""
import ipaddress
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseForbidden

logger = logging.getLogger('keel.security')


def _get_client_ip(request):
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


class SecurityHeadersMiddleware:
    """Adds security headers beyond what Django's SecurityMiddleware provides."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Content Security Policy — restrictive default, products can override
        if not response.has_header('Content-Security-Policy'):
            csp = getattr(settings, 'KEEL_CSP_POLICY', None)
            if csp:
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
        ip = _get_client_ip(request)

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
    Pull the client IP from a trusted proxy header — see _get_client_ip.
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
            ip = _get_client_ip(request)
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
                return HttpResponseForbidden('Access denied.', content_type='text/plain')

        return self.get_response(request)
