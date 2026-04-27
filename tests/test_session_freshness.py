"""Tests for ``keel.accounts.middleware.SessionFreshnessMiddleware``.

The middleware exists so that signing out of one DockLabs product
propagates to the others. Each product holds its own Django session
cookie scoped to its own subdomain; without a freshness check, peer
products keep trusting the local session for ``SESSION_COOKIE_AGE``
(default 30 days) regardless of what the IdP did.

These tests exercise the middleware in isolation — no live HTTP — by
patching the Keel lookup and the cache.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _build_request(path='/dashboard/', user=None, session=None):
    request = RequestFactory().get(path)
    request.user = user or _AnonymousUser()
    request.session = session if session is not None else {}
    return request


class _AnonymousUser:
    is_authenticated = False
    is_anonymous = True


class _AuthedUser:
    is_authenticated = True
    is_anonymous = False
    pk = 'user-pk'

    def __str__(self):
        return 'authed-user'


@override_settings(KEEL_OIDC_CLIENT_ID='', KEEL_OIDC_CLIENT_SECRET='')
def test_noop_when_oidc_not_configured():
    """Standalone deployment: middleware must not call Keel."""
    from keel.accounts.middleware import SessionFreshnessMiddleware

    mw = SessionFreshnessMiddleware(lambda r: HttpResponse('ok'))
    assert mw.enabled is False

    with patch.object(SessionFreshnessMiddleware, '_call_keel') as mocked:
        response = mw(_build_request(user=_AuthedUser()))

    mocked.assert_not_called()
    assert response.status_code == 200


@override_settings(
    KEEL_OIDC_CLIENT_ID='client', KEEL_OIDC_CLIENT_SECRET='secret',
    KEEL_OIDC_ISSUER='https://keel.example.com', DEMO_MODE=True,
)
def test_noop_in_demo_mode():
    from keel.accounts.middleware import SessionFreshnessMiddleware

    mw = SessionFreshnessMiddleware(lambda r: HttpResponse('ok'))
    assert mw.enabled is False


@override_settings(
    KEEL_OIDC_CLIENT_ID='client', KEEL_OIDC_CLIENT_SECRET='secret',
    KEEL_OIDC_ISSUER='https://keel.example.com', DEMO_MODE=False,
)
def test_noop_when_session_lacks_oidc_marker():
    """Local-form sign-ins have no ``keel_oidc_login_at``; nothing to compare."""
    from keel.accounts.middleware import SessionFreshnessMiddleware

    mw = SessionFreshnessMiddleware(lambda r: HttpResponse('ok'))
    request = _build_request(user=_AuthedUser(), session={})

    with patch.object(SessionFreshnessMiddleware, '_call_keel') as mocked:
        response = mw(request)

    mocked.assert_not_called()
    assert response.status_code == 200


@override_settings(
    KEEL_OIDC_CLIENT_ID='client', KEEL_OIDC_CLIENT_SECRET='secret',
    KEEL_OIDC_ISSUER='https://keel.example.com', DEMO_MODE=False,
)
def test_logs_user_out_when_keel_logout_is_newer():
    from keel.accounts.middleware import SessionFreshnessMiddleware

    login_at = timezone.now() - timedelta(minutes=5)
    keel_logout_at = timezone.now() - timedelta(minutes=1)

    session = {
        'keel_oidc_login_at': login_at.isoformat(),
        'keel_oidc_claims': {'sub': 'user-sub-123', 'product_access': {}},
    }
    request = _build_request(user=_AuthedUser(), session=session)

    mw = SessionFreshnessMiddleware(lambda r: HttpResponse('ok'))
    with patch('keel.accounts.middleware.auth_logout') as mocked_logout, \
         patch.object(SessionFreshnessMiddleware, '_call_keel',
                      return_value=keel_logout_at):
        response = mw(request)

    mocked_logout.assert_called_once_with(request)
    assert response.status_code == 302
    assert response['Location'].startswith('/accounts/login/?next=')


@override_settings(
    KEEL_OIDC_CLIENT_ID='client', KEEL_OIDC_CLIENT_SECRET='secret',
    KEEL_OIDC_ISSUER='https://keel.example.com', DEMO_MODE=False,
)
def test_passes_through_when_keel_logout_predates_session_login():
    """User logged out at Keel earlier, then signed back in here later."""
    from keel.accounts.middleware import SessionFreshnessMiddleware

    keel_logout_at = timezone.now() - timedelta(hours=1)
    login_at = timezone.now() - timedelta(minutes=5)

    session = {
        'keel_oidc_login_at': login_at.isoformat(),
        'keel_oidc_claims': {'sub': 'user-sub-123', 'product_access': {}},
    }
    request = _build_request(user=_AuthedUser(), session=session)

    mw = SessionFreshnessMiddleware(lambda r: HttpResponse('ok'))
    with patch.object(SessionFreshnessMiddleware, '_call_keel',
                      return_value=keel_logout_at):
        response = mw(request)

    assert response.status_code == 200


@override_settings(
    KEEL_OIDC_CLIENT_ID='client', KEEL_OIDC_CLIENT_SECRET='secret',
    KEEL_OIDC_ISSUER='https://keel.example.com', DEMO_MODE=False,
)
def test_fails_open_when_keel_unreachable():
    """A Keel outage must NOT lock users out of every other product."""
    from keel.accounts.middleware import SessionFreshnessMiddleware

    session = {
        'keel_oidc_login_at': timezone.now().isoformat(),
        'keel_oidc_claims': {'sub': 'user-sub-123', 'product_access': {}},
    }
    request = _build_request(user=_AuthedUser(), session=session)

    mw = SessionFreshnessMiddleware(lambda r: HttpResponse('ok'))
    with patch.object(SessionFreshnessMiddleware, '_call_keel',
                      side_effect=RuntimeError('keel down')):
        response = mw(request)

    assert response.status_code == 200


@override_settings(
    KEEL_OIDC_CLIENT_ID='client', KEEL_OIDC_CLIENT_SECRET='secret',
    KEEL_OIDC_ISSUER='https://keel.example.com', DEMO_MODE=False,
)
def test_lookup_is_cached_per_sub():
    """Two requests for the same sub should hit Keel exactly once."""
    from keel.accounts.middleware import SessionFreshnessMiddleware

    session = {
        'keel_oidc_login_at': timezone.now().isoformat(),
        'keel_oidc_claims': {'sub': 'user-sub-123', 'product_access': {}},
    }

    mw = SessionFreshnessMiddleware(lambda r: HttpResponse('ok'))
    with patch.object(SessionFreshnessMiddleware, '_call_keel',
                      return_value=None) as mocked:
        mw(_build_request(user=_AuthedUser(), session=session))
        mw(_build_request(user=_AuthedUser(), session=session))

    assert mocked.call_count == 1
