"""Tests for Phase B: login-time one-shot AI-key hydration.

``keel.core.sso._maybe_hydrate_local_ai_key`` spends the login-fresh OIDC
access token (held in memory by allauth even with
``SOCIALACCOUNT_STORE_TOKENS=False``) to copy the user's Anthropic key from
Keel into the product-LOCAL encrypted field, then discards the token. This
is what delivers "enter once, see everywhere" without any token at rest.

It runs only for ``KEEL_LOCAL_AI_KEY`` products, only for the Keel provider,
only when the local field is empty, and only when a token is present — and
never blocks login on failure.

Also covers the explicit-token fetch helper
``keel.core.ai.fetch_ai_key_with_token`` (transport guards + return shape).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.test import override_settings

pytest.importorskip('cryptography')

SUITE = dict(KEEL_OIDC_CLIENT_ID='test-client', KEEL_IS_IDP=False, DEMO_MODE=False)


def _gen_key():
    from keel.security.encryption import generate_key
    return generate_key()


@pytest.fixture
def user(db, settings):
    from keel.accounts.models import KeelUser, Organization
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    org = Organization.objects.create(slug='hydrate-org', name='Test')
    return KeelUser.objects.create(
        username='hydrate-user', email='hydrate@example.test', organization=org,
    )


def _sociallogin(user, *, provider='keel', token='login-fresh-token'):
    tok = SimpleNamespace(token=token) if token is not None else None
    return SimpleNamespace(
        user=user,
        token=tok,
        account=SimpleNamespace(provider=provider),
    )


# ---------------------------------------------------------------------------
# fetch_ai_key_with_token — explicit-token variant
# ---------------------------------------------------------------------------
def test_fetch_with_token_empty_token_returns_blank():
    from keel.core.ai import fetch_ai_key_with_token
    assert fetch_ai_key_with_token('') == ''


def test_fetch_with_token_refuses_unsafe_issuer(settings, caplog):
    from keel.core.ai import fetch_ai_key_with_token
    settings.DEBUG = False
    settings.KEEL_OIDC_ISSUER = 'http://attacker.example.com'
    with caplog.at_level('ERROR'):
        assert fetch_ai_key_with_token('tok-that-must-not-leak') == ''
    assert any('must use https' in r.message for r in caplog.records)


def test_fetch_with_token_happy_path(settings, monkeypatch):
    from keel.core import ai as ai_mod
    settings.DEBUG = False
    settings.KEEL_OIDC_ISSUER = 'https://keel.docklabs.ai'

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"key": "sk-ant-hydrated-1234567890"}'

    class _Opener:
        def open(self, req, timeout=None):
            # The token must ride in the Authorization header.
            assert req.headers['Authorization'] == 'Bearer the-token'
            return _Resp()

    monkeypatch.setattr(ai_mod, '_build_no_redirect_opener', lambda: _Opener())
    assert ai_mod.fetch_ai_key_with_token('the-token') == 'sk-ant-hydrated-1234567890'


# ---------------------------------------------------------------------------
# _maybe_hydrate_local_ai_key — gating
# ---------------------------------------------------------------------------
def test_hydration_noop_when_flag_off(db, user, monkeypatch):
    from keel.core import sso
    monkeypatch.setattr(
        'keel.core.ai.fetch_ai_key_with_token', lambda t: 'sk-ant-should-not-be-used',
    )
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=False):
        sso._maybe_hydrate_local_ai_key(_sociallogin(user))
    user.refresh_from_db()
    assert user.has_anthropic_key() is False


def test_hydration_noop_for_non_keel_provider(db, user, monkeypatch):
    from keel.core import sso
    monkeypatch.setattr(
        'keel.core.ai.fetch_ai_key_with_token', lambda t: 'sk-ant-should-not-be-used',
    )
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        sso._maybe_hydrate_local_ai_key(_sociallogin(user, provider='microsoft'))
    user.refresh_from_db()
    assert user.has_anthropic_key() is False


def test_hydration_noop_when_no_token(db, user, monkeypatch):
    from keel.core import sso
    called = {'n': 0}

    def _fetch(t):
        called['n'] += 1
        return 'sk-ant-x'
    monkeypatch.setattr('keel.core.ai.fetch_ai_key_with_token', _fetch)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        sso._maybe_hydrate_local_ai_key(_sociallogin(user, token=None))
    user.refresh_from_db()
    assert user.has_anthropic_key() is False
    assert called['n'] == 0  # never even attempted the fetch


def test_hydration_does_not_clobber_existing_local_key(db, user, settings, monkeypatch):
    from keel.core import sso
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    user.anthropic_api_key = 'sk-ant-already-local-1234567890'
    user.save(update_fields=['anthropic_api_key_encrypted'])
    monkeypatch.setattr(
        'keel.core.ai.fetch_ai_key_with_token', lambda t: 'sk-ant-from-keel-DIFFERENT',
    )
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        sso._maybe_hydrate_local_ai_key(_sociallogin(user))
    user.refresh_from_db()
    assert user.anthropic_api_key == 'sk-ant-already-local-1234567890'


# ---------------------------------------------------------------------------
# _maybe_hydrate_local_ai_key — the happy path + failure isolation
# ---------------------------------------------------------------------------
def test_hydration_writes_local_field_on_success(db, user, settings, monkeypatch):
    from keel.core import sso
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    seen = {}

    def _fetch(t):
        seen['token'] = t
        return 'sk-ant-hydrated-from-keel-1234567890'
    monkeypatch.setattr('keel.core.ai.fetch_ai_key_with_token', _fetch)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        sso._maybe_hydrate_local_ai_key(_sociallogin(user, token='login-fresh-token'))
    user.refresh_from_db()
    assert user.has_anthropic_key() is True
    assert user.anthropic_api_key == 'sk-ant-hydrated-from-keel-1234567890'
    assert seen['token'] == 'login-fresh-token'  # used the in-memory login token


def test_hydration_no_key_on_keel_leaves_field_empty(db, user, monkeypatch):
    from keel.core import sso
    monkeypatch.setattr('keel.core.ai.fetch_ai_key_with_token', lambda t: '')
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        sso._maybe_hydrate_local_ai_key(_sociallogin(user))
    user.refresh_from_db()
    assert user.has_anthropic_key() is False


def test_hydration_never_raises_on_fetch_error(db, user, settings, monkeypatch):
    """A fetch blowing up must not propagate — login must never break."""
    from keel.core import sso
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()

    def _boom(t):
        raise RuntimeError('network exploded')
    monkeypatch.setattr('keel.core.ai.fetch_ai_key_with_token', _boom)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        # Should swallow the exception, not raise.
        sso._maybe_hydrate_local_ai_key(_sociallogin(user))
    user.refresh_from_db()
    assert user.has_anthropic_key() is False
