"""
Keel Security Compliance — health checks and configuration validation.

Verifies that a DockLabs product has proper security configuration.
Reports compliance gaps that need attention.

Usage:
    from keel.security.compliance import run_security_audit
    results = run_security_audit()
    for check in results:
        print(f'{check.status} {check.name}: {check.message}')
"""
import logging

from django.conf import settings

logger = logging.getLogger('keel.security')


class ComplianceCheck:
    PASS = 'PASS'
    FAIL = 'FAIL'
    WARN = 'WARN'

    def __init__(self, name, status, message, category=''):
        self.name = name
        self.status = status
        self.message = message
        self.category = category

    def __str__(self):
        icon = {'PASS': '\u2705', 'FAIL': '\u274c', 'WARN': '\u26a0\ufe0f'}.get(self.status, '?')
        return f'{icon} [{self.status}] {self.name}: {self.message}'


def _check(name, condition, pass_msg, fail_msg, category='', warn=False):
    if condition:
        return ComplianceCheck(name, ComplianceCheck.PASS, pass_msg, category)
    status = ComplianceCheck.WARN if warn else ComplianceCheck.FAIL
    return ComplianceCheck(name, status, fail_msg, category)


def check_django_security():
    """Verify Django security settings."""
    checks = []
    is_prod = not getattr(settings, 'DEBUG', True)

    checks.append(_check(
        'DEBUG disabled',
        not getattr(settings, 'DEBUG', True),
        'DEBUG is False',
        'DEBUG is True — must be False in production',
        'django',
    ))

    checks.append(_check(
        'Secret key configured',
        len(getattr(settings, 'SECRET_KEY', '')) >= 40,
        'SECRET_KEY is set and sufficient length',
        'SECRET_KEY is too short or missing',
        'django',
    ))

    if is_prod:
        checks.append(_check(
            'SECURE_HSTS_SECONDS',
            getattr(settings, 'SECURE_HSTS_SECONDS', 0) >= 31536000,
            f'HSTS set to {getattr(settings, "SECURE_HSTS_SECONDS", 0)}s',
            'HSTS not set or less than 1 year',
            'django',
        ))

        checks.append(_check(
            'Secure session cookies',
            getattr(settings, 'SESSION_COOKIE_SECURE', False),
            'SESSION_COOKIE_SECURE is True',
            'SESSION_COOKIE_SECURE should be True in production',
            'django',
        ))

        checks.append(_check(
            'Secure CSRF cookies',
            getattr(settings, 'CSRF_COOKIE_SECURE', False),
            'CSRF_COOKIE_SECURE is True',
            'CSRF_COOKIE_SECURE should be True in production',
            'django',
        ))

        checks.append(_check(
            'Session timeout',
            getattr(settings, 'SESSION_COOKIE_AGE', 1209600) <= 3600,
            f'Session timeout: {getattr(settings, "SESSION_COOKIE_AGE", 1209600)}s',
            'Session timeout exceeds 1 hour — reduce for security',
            'django',
            warn=True,
        ))

    checks.append(_check(
        'Password validators',
        len(getattr(settings, 'AUTH_PASSWORD_VALIDATORS', [])) >= 3,
        f'{len(getattr(settings, "AUTH_PASSWORD_VALIDATORS", []))} password validators configured',
        'Insufficient password validators (need at least 3)',
        'django',
    ))

    return checks


def check_keel_security():
    """Verify Keel security middleware and features."""
    checks = []
    middleware = getattr(settings, 'MIDDLEWARE', [])

    checks.append(_check(
        'Audit middleware',
        any('AuditMiddleware' in m for m in middleware),
        'AuditMiddleware is active',
        'AuditMiddleware not found in MIDDLEWARE',
        'keel',
    ))

    checks.append(_check(
        'Security headers middleware',
        any('SecurityHeadersMiddleware' in m for m in middleware),
        'SecurityHeadersMiddleware is active',
        'SecurityHeadersMiddleware not in MIDDLEWARE — add keel.security.middleware.SecurityHeadersMiddleware',
        'keel',
        warn=True,
    ))

    checks.append(_check(
        'Failed login monitor',
        any('FailedLoginMonitor' in m for m in middleware),
        'FailedLoginMonitor is active',
        'FailedLoginMonitor not in MIDDLEWARE — brute force protection disabled',
        'keel',
    ))

    checks.append(_check(
        'File scanning configured',
        getattr(settings, 'KEEL_FILE_SCANNING_ENABLED', None) is not None,
        'File scanning is explicitly configured',
        'KEEL_FILE_SCANNING_ENABLED not set — defaults to True in production',
        'keel',
        warn=True,
    ))

    checks.append(_check(
        'Security alert recipients',
        bool(getattr(settings, 'KEEL_SECURITY_ALERT_RECIPIENTS', [])),
        'Security alerts will be sent to configured recipients',
        'KEEL_SECURITY_ALERT_RECIPIENTS not set — no one will receive security alerts',
        'keel',
    ))

    checks.append(_check(
        'Demo mode disabled',
        not getattr(settings, 'DEMO_MODE', False),
        'DEMO_MODE is disabled',
        'DEMO_MODE is enabled — quick-login cards are a security risk in production',
        'keel',
    ))

    return checks


def check_authentication():
    """Verify authentication configuration."""
    checks = []
    installed = getattr(settings, 'INSTALLED_APPS', [])

    checks.append(_check(
        'MFA available',
        'allauth.mfa' in installed,
        'MFA is available (allauth.mfa installed)',
        'MFA not available — install allauth.mfa',
        'auth',
    ))

    checks.append(_check(
        'SSO configured',
        'allauth.socialaccount' in installed,
        'Social/SSO authentication available',
        'SSO not configured',
        'auth',
        warn=True,
    ))

    return checks


def run_security_audit():
    """Run all compliance checks and return results."""
    results = []
    results.extend(check_django_security())
    results.extend(check_keel_security())
    results.extend(check_authentication())

    passed = sum(1 for r in results if r.status == ComplianceCheck.PASS)
    failed = sum(1 for r in results if r.status == ComplianceCheck.FAIL)
    warned = sum(1 for r in results if r.status == ComplianceCheck.WARN)

    logger.info(
        'Security audit: %d passed, %d failed, %d warnings (of %d checks)',
        passed, failed, warned, len(results),
    )

    return results
