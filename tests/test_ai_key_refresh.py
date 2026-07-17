"""Tests for the self-healing ``ai_key_present`` claim refresh and the AI
settings-URL fix.

Two defects are covered:

- **Stale claim (false "needs key" prompt).** ``ai_key_present`` is a
  login-time snapshot; setting the key on Keel afterwards didn't propagate
  mid-session. ``keel.core.ai_key_refresh.refresh_ai_key_claim`` corrects a
  stale ``False`` claim (and only ever in that direction), gated by
  ``AIKeyClaimRefreshMiddleware``.
- **Mis-routed link.** ``_ai_settings_url`` linked to ``/settings/?panel=ai``,
  which the slug-based settings router ignores — bouncing the user to the
  first panel (Profile). It must carry the ``ai`` slug in the path.
"""
import time

import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from keel.accounts.models import KeelUser

SUITE = dict(
    KEEL_OIDC_CLIENT_ID='client', KEEL_OIDC_CLIENT_SECRET='secret',
    KEEL_OIDC_ISSUER='https://keel.example.com', DEMO_MODE=False,
)


# --------------------------------------------------------------------------
# refresh_ai_key_claim — corrective-only claim heal
# --------------------------------------------------------------------------
@pytest.fixture
def keel_user(db):
    return KeelUser.objects.create(
        username='ai-refresh-user', email='air@example.test',
        is_superuser=True, is_staff=True,
    )


def _make_account(user, present):
    from allauth.socialaccount.models import SocialAccount
    return SocialAccount.objects.create(
        user=user, provider='keel', uid=f'sub-{user.pk}',
        extra_data={'userinfo': {'ai_key_present': present}},
    )


def _read_claim(account):
    account.refresh_from_db()
    return account.extra_data.get('userinfo', {}).get('ai_key_present')


@override_settings(KEEL_OIDC_ISSUER='https://keel.example.com')
def test_flips_stale_false_to_true_when_key_present(keel_user, monkeypatch):
    account = _make_account(keel_user, present=False)
    import keel.core.ai as ai_mod
    monkeypatch.setattr(ai_mod, '_fetch_key_from_keel', lambda u, r: 'sk-ant-xyz')

    from keel.core.ai_key_refresh import refresh_ai_key_claim
    assert refresh_ai_key_claim(keel_user) is True
    assert _read_claim(account) is True


@override_settings(KEEL_OIDC_ISSUER='https://keel.example.com')
def test_no_key_leaves_claim_untouched(keel_user, monkeypatch):
    """A negative/failed fetch must never write a False (no false negatives)."""
    account = _make_account(keel_user, present=False)
    import keel.core.ai as ai_mod
    monkeypatch.setattr(ai_mod, '_fetch_key_from_keel', lambda u, r: '')

    from keel.core.ai_key_refresh import refresh_ai_key_claim
    assert refresh_ai_key_claim(keel_user) is None
    assert _read_claim(account) is False  # unchanged


@override_settings(KEEL_OIDC_ISSUER='')
def test_noop_without_issuer(keel_user, monkeypatch):
    """Standalone deployment: short-circuit before any network call."""
    _make_account(keel_user, present=False)
    import keel.core.ai as ai_mod
    called = {'n': 0}

    def _spy(u, r):
        called['n'] += 1
        return 'sk-ant'

    monkeypatch.setattr(ai_mod, '_fetch_key_from_keel', _spy)
    from keel.core.ai_key_refresh import refresh_ai_key_claim
    assert refresh_ai_key_claim(keel_user) is None
    assert called['n'] == 0


@override_settings(KEEL_OIDC_ISSUER='https://keel.example.com')
def test_noop_without_keel_social_account(keel_user, monkeypatch):
    import keel.core.ai as ai_mod
    monkeypatch.setattr(ai_mod, '_fetch_key_from_keel', lambda u, r: 'sk-ant')
    from keel.core.ai_key_refresh import refresh_ai_key_claim
    assert refresh_ai_key_claim(keel_user) is None


# --------------------------------------------------------------------------
# AIKeyClaimRefreshMiddleware — gating + safety
# --------------------------------------------------------------------------
class _AuthedUser:
    is_authenticated = True
    is_anonymous = False
    pk = 'u1'


class _Anon:
    is_authenticated = False
    is_anonymous = True


def _req(user, session=None):
    r = RequestFactory().get('/companies/santander/')
    r.user = user
    r.session = session if session is not None else {}
    return r


def _mw():
    from keel.accounts.middleware import AIKeyClaimRefreshMiddleware
    return AIKeyClaimRefreshMiddleware(lambda r: HttpResponse('ok'))


@override_settings(**SUITE)
def test_mw_calls_refresh_when_needs_key(monkeypatch):
    import keel.core.ai_access as access_mod
    import keel.core.ai_key_refresh as refresh_mod
    monkeypatch.setattr(access_mod, 'user_ai_state', lambda u, *a, **k: 'needs_key')
    calls = {'n': 0}
    monkeypatch.setattr(refresh_mod, 'refresh_ai_key_claim',
                        lambda u: calls.__setitem__('n', calls['n'] + 1))

    resp = _mw()(_req(_AuthedUser()))
    assert resp.status_code == 200
    assert calls['n'] == 1


@override_settings(**SUITE)
def test_mw_skips_refresh_when_ready(monkeypatch):
    import keel.core.ai_access as access_mod
    import keel.core.ai_key_refresh as refresh_mod
    monkeypatch.setattr(access_mod, 'user_ai_state', lambda u, *a, **k: 'ready')
    calls = {'n': 0}
    monkeypatch.setattr(refresh_mod, 'refresh_ai_key_claim',
                        lambda u: calls.__setitem__('n', calls['n'] + 1))

    session = {}
    resp = _mw()(_req(_AuthedUser(), session))
    assert resp.status_code == 200
    assert calls['n'] == 0
    # Still marked checked so a keyed/AI-less user isn't re-evaluated for TTL.
    assert '_ai_key_checked_at' in session


@override_settings(**SUITE)
def test_mw_respects_ttl(monkeypatch):
    """A recent check timestamp skips the state lookup and the refresh."""
    import keel.core.ai_access as access_mod
    import keel.core.ai_key_refresh as refresh_mod
    state_calls = {'n': 0}
    refresh_calls = {'n': 0}
    monkeypatch.setattr(access_mod, 'user_ai_state',
                        lambda *a, **k: (state_calls.__setitem__('n', state_calls['n'] + 1), 'needs_key')[1])
    monkeypatch.setattr(refresh_mod, 'refresh_ai_key_claim',
                        lambda u: refresh_calls.__setitem__('n', refresh_calls['n'] + 1))

    session = {'_ai_key_checked_at': time.time()}
    resp = _mw()(_req(_AuthedUser(), session))
    assert resp.status_code == 200
    assert state_calls['n'] == 0
    assert refresh_calls['n'] == 0


@override_settings(KEEL_OIDC_CLIENT_ID='', DEMO_MODE=False)
def test_mw_noop_when_standalone(monkeypatch):
    import keel.core.ai_key_refresh as refresh_mod
    calls = {'n': 0}
    monkeypatch.setattr(refresh_mod, 'refresh_ai_key_claim',
                        lambda u: calls.__setitem__('n', calls['n'] + 1))
    resp = _mw()(_req(_AuthedUser()))
    assert resp.status_code == 200
    assert calls['n'] == 0


@override_settings(**SUITE)
def test_mw_noop_when_anonymous(monkeypatch):
    import keel.core.ai_key_refresh as refresh_mod
    calls = {'n': 0}
    monkeypatch.setattr(refresh_mod, 'refresh_ai_key_claim',
                        lambda u: calls.__setitem__('n', calls['n'] + 1))
    resp = _mw()(_req(_Anon()))
    assert resp.status_code == 200
    assert calls['n'] == 0


@override_settings(**SUITE)
def test_mw_never_raises(monkeypatch):
    import keel.core.ai_access as access_mod
    import keel.core.ai_key_refresh as refresh_mod
    monkeypatch.setattr(access_mod, 'user_ai_state', lambda *a, **k: 'needs_key')

    def _boom(u):
        raise RuntimeError('keel down')

    monkeypatch.setattr(refresh_mod, 'refresh_ai_key_claim', _boom)
    resp = _mw()(_req(_AuthedUser()))
    assert resp.status_code == 200  # exception swallowed


# --------------------------------------------------------------------------
# _ai_settings_url — path-slug link fix (Defect B)
# --------------------------------------------------------------------------
@override_settings(**SUITE)
def test_ai_settings_url_suite_uses_path_slug():
    from keel.core.templatetags.keel_tags import _ai_settings_url
    url = _ai_settings_url()
    assert url == 'https://keel.example.com/settings/ai/'
    assert '?panel=' not in url


@override_settings(KEEL_OIDC_CLIENT_ID='', DEMO_MODE=False)
def test_ai_settings_url_standalone_reverses_panel_slug():
    from keel.core.templatetags.keel_tags import _ai_settings_url
    url = _ai_settings_url()
    assert url.endswith('/settings/ai/')
    assert '?panel=' not in url
