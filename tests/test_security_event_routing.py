"""Failed-login and security-event routing to Activity (Approach D, v0.46.0).

Under Approach D, FailedLoginMonitor records and AdminIPAllowlistMiddleware
denials write Activity rows via ``record_system_event``, NOT AuditLog. The
abstract AuditLog schema now rejects NULL-user rows entirely, so these
events have no home there anyway.

Verbs:
- ``auth.login_failed`` — per failed-attempt (status='warn')
- ``security.account_locked`` — fired when the lockout threshold is hit
  (status='failed', triggers system_admin notification fan-out)
- ``security.suspicious_activity`` — admin allowlist denials
"""
from unittest.mock import patch

import pytest


def test_failed_login_records_activity_via_record_system_event():
    """Each `_record_failure` call emits one Activity row with verb=auth.login_failed."""
    from django.core.cache import cache
    from keel.security.middleware import FailedLoginMonitor

    cache.clear()
    monitor = FailedLoginMonitor(lambda r: None)

    with patch('keel.activity.services.record_system_event') as m:
        monitor._record_failure('10.0.0.5')

    # The first call records a single auth.login_failed Activity row.
    auth_calls = [
        c for c in m.call_args_list
        if c.kwargs.get('verb') == 'auth.login_failed'
    ]
    assert len(auth_calls) == 1
    kw = auth_calls[0].kwargs
    assert kw['status'] == 'warn'
    assert kw['metadata']['ip'] == '10.0.0.5'
    assert 'failures_in_window' in kw['metadata']


def test_lockout_threshold_emits_account_locked_activity():
    """Hitting max_failures emits security.account_locked (status='failed')."""
    from django.core.cache import cache
    from keel.security.middleware import FailedLoginMonitor

    cache.clear()
    monitor = FailedLoginMonitor(lambda r: None)
    monitor.max_failures = 3  # tighten so the test triggers quickly

    ip = '10.0.0.6'
    with patch('keel.activity.services.record_system_event') as m:
        monitor._record_failure(ip)
        monitor._record_failure(ip)
        monitor._record_failure(ip)  # this trips lockout

    locked_calls = [
        c for c in m.call_args_list
        if c.kwargs.get('verb') == 'security.account_locked'
    ]
    assert len(locked_calls) == 1, (
        'security.account_locked must fire exactly once on threshold hit'
    )
    kw = locked_calls[0].kwargs
    assert kw['status'] == 'failed', (
        'Lockout is a failed status so the Activity → Notification seam '
        'fans it out to product system_admins.'
    )
    assert kw['metadata']['ip'] == ip
    assert kw['metadata']['failures'] >= 3


def test_admin_ip_denial_records_suspicious_activity():
    """AdminIPAllowlistMiddleware denials emit security.suspicious_activity."""
    from django.test import RequestFactory
    from django.test.utils import override_settings
    from keel.security.middleware import AdminIPAllowlistMiddleware

    with override_settings(KEEL_ADMIN_ALLOWED_IPS=['127.0.0.1']):
        rf = RequestFactory()
        request = rf.get('/admin/')
        request.META['REMOTE_ADDR'] = '203.0.113.99'  # not in allowlist

        called_response = []
        def get_response(req):
            called_response.append(True)
            return None

        middleware = AdminIPAllowlistMiddleware(get_response)

        with patch('keel.activity.services.record_system_event') as m:
            resp = middleware(request)

    # 403 returned, get_response never called
    assert resp.status_code == 403
    assert not called_response

    # security.suspicious_activity activity row emitted
    suspicious = [
        c for c in m.call_args_list
        if c.kwargs.get('verb') == 'security.suspicious_activity'
    ]
    assert len(suspicious) == 1
    kw = suspicious[0].kwargs
    assert kw['status'] == 'warn'
    assert kw['metadata']['ip'] == '203.0.113.99'
    assert kw['metadata']['event_type'] == 'admin_access_denied'


def test_activity_emission_failure_does_not_break_middleware():
    """A botched record_system_event call must NOT raise — the middleware's
    primary job (lockout) keeps working even if Activity emission fails."""
    from django.core.cache import cache
    from keel.security.middleware import FailedLoginMonitor

    cache.clear()
    monitor = FailedLoginMonitor(lambda r: None)

    # Force record_system_event to raise; lockout machinery should still work.
    with patch(
        'keel.activity.services.record_system_event',
        side_effect=RuntimeError('boom'),
    ):
        # Should not raise.
        monitor._record_failure('10.0.0.7')


def test_check_failed_logins_reads_activity_when_configured(settings):
    """``check_failed_logins`` should prefer Activity over AuditLog under D."""
    from unittest.mock import MagicMock
    from keel.security.alerts import check_failed_logins

    # Build a fake Activity model with the auth.login_failed verb.
    fake_activity = MagicMock()
    qs_chain = MagicMock()
    fake_activity.objects.filter.return_value = qs_chain
    qs_chain.values.return_value = qs_chain
    qs_chain.annotate.return_value = qs_chain
    qs_chain.filter.return_value = [
        {'metadata__ip': '4.4.4.4', 'count': 9},
    ]

    alerts = check_failed_logins(
        audit_log_model=None,
        window_minutes=15,
        threshold=5,
        activity_model=fake_activity,
    )

    # We hit the Activity path (Approach D), not the legacy AuditLog path.
    fake_activity.objects.filter.assert_called_once()
    kwargs = fake_activity.objects.filter.call_args.kwargs
    assert kwargs['verb'] == 'auth.login_failed'
    assert len(alerts) == 1
    assert alerts[0].details['ip'] == '4.4.4.4'
    assert alerts[0].details['count'] == 9
