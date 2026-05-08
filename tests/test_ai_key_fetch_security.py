"""Tests for the security guards on the cross-product key fetch.

Locks two contracts in `keel.core.ai._fetch_key_from_keel`:

1. **HTTPS allowlist.** A non-https ``KEEL_OIDC_ISSUER`` outside DEBUG
   mode and outside localhost MUST refuse to send the bearer token —
   leaking it over plaintext is the failure mode CSO finding #4 closes.
2. **No redirects.** The custom opener installs a redirect handler that
   raises, so a misconfigured / compromised issuer cannot bounce the
   request to an attacker host with the ``Authorization`` header still
   attached.

Also covers `keel.ai.views._resolve_token_user` using django-oauth-
toolkit's canonical ``_load_access_token`` helper — the regression test
for CSO finding #1 (forward-compat against the ``token_checksum``
column becoming the only lookup index).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def fake_user(db):
    """Minimal authenticated-shaped object — we don't call DB for these tests."""
    class _U:
        is_authenticated = True
        anthropic_api_key = ''  # forces the cross-product fetch path
        def has_anthropic_key(self):
            return False
    return _U()


def test_fetch_refuses_plaintext_issuer_outside_debug(settings, fake_user, caplog):
    """`http://` issuer outside DEBUG must NOT send the bearer token."""
    from keel.core.ai import _fetch_key_from_keel

    settings.DEBUG = False
    settings.KEEL_OIDC_ISSUER = 'http://attacker.example.com'

    # Stub _user_access_token so we'd otherwise have a token to leak.
    import keel.core.ai as ai_mod
    original = ai_mod._user_access_token
    ai_mod._user_access_token = lambda user: 'bearer-token-that-must-not-leak'
    try:
        with caplog.at_level('ERROR'):
            result = _fetch_key_from_keel(fake_user, request=None)
    finally:
        ai_mod._user_access_token = original

    assert result == ''
    # Loud log so misconfiguration is detectable in deploy review.
    assert any(
        'must use https' in rec.message and 'attacker.example.com' in rec.message
        for rec in caplog.records
    )


def test_fetch_allows_https_issuer(settings, fake_user, monkeypatch):
    """`https://` issuer reaches the urllib opener (we stop it short with a stub)."""
    from keel.core.ai import _fetch_key_from_keel
    import keel.core.ai as ai_mod

    settings.DEBUG = False
    settings.KEEL_OIDC_ISSUER = 'https://keel.docklabs.ai'

    monkeypatch.setattr(ai_mod, '_user_access_token', lambda user: 'tok')

    sentinel = {'opened': False}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"key": "sk-ant-fake"}'

    class _Opener:
        def open(self, req, timeout):
            sentinel['opened'] = True
            return _Resp()

    monkeypatch.setattr(ai_mod, '_build_no_redirect_opener', lambda: _Opener())

    result = _fetch_key_from_keel(fake_user, request=None)
    assert result == 'sk-ant-fake'
    assert sentinel['opened'] is True


def test_fetch_allows_localhost_in_dev(settings, fake_user, monkeypatch):
    """`http://localhost` is permitted regardless of DEBUG (dev workflow)."""
    from keel.core.ai import _fetch_key_from_keel
    import keel.core.ai as ai_mod

    settings.DEBUG = False  # explicitly NOT debug
    settings.KEEL_OIDC_ISSUER = 'http://localhost:8000'

    monkeypatch.setattr(ai_mod, '_user_access_token', lambda user: 'tok')

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"key": "sk-ant-dev"}'

    class _Opener:
        def open(self, req, timeout):
            return _Resp()

    monkeypatch.setattr(ai_mod, '_build_no_redirect_opener', lambda: _Opener())

    assert _fetch_key_from_keel(fake_user, request=None) == 'sk-ant-dev'


def test_no_redirect_opener_raises_on_redirect():
    """The redirect handler must raise rather than follow with the auth header."""
    import io
    import urllib.error

    from keel.core.ai import _build_no_redirect_opener

    opener = _build_no_redirect_opener()
    handler = next(
        h for h in opener.handlers
        if h.__class__.__name__ == '_NoRedirect'
    )
    # Reach into the handler with a synthesised redirect call.
    import urllib.request
    req = urllib.request.Request('https://keel.docklabs.ai/api/v1/ai/key/')
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        handler.redirect_request(
            req, io.BytesIO(b''), 302, 'Found', {},
            'https://attacker.example.com/api/v1/ai/key/',
        )
    assert 'redirect' in str(exc_info.value).lower()
    assert 'blocked' in str(exc_info.value).lower()


def test_resolve_token_user_uses_oauth_toolkit_canonical_lookup(monkeypatch):
    """`_resolve_token_user` must call `OAuth2Validator._load_access_token`."""
    from keel.ai import views as ai_views

    calls = {'load_called_with': None, 'is_valid_called_with': None}

    class _FakeAccessToken:
        user = type('U', (), {'is_authenticated': True})()
        application = type('A', (), {'client_id': 'beacon-client'})()

        def is_valid(self, scopes):
            calls['is_valid_called_with'] = list(scopes)
            return True

    class _FakeValidator:
        def _load_access_token(self, token):
            calls['load_called_with'] = token
            return _FakeAccessToken()

    monkeypatch.setattr(
        'oauth2_provider.oauth2_validators.OAuth2Validator',
        _FakeValidator,
    )

    class _Req:
        META = {'HTTP_AUTHORIZATION': 'Bearer my-token-12345'}

    user, app_id = ai_views._resolve_token_user(_Req())
    assert user is not None
    assert app_id == 'beacon-client'
    assert calls['load_called_with'] == 'my-token-12345'
    assert calls['is_valid_called_with'] == ['ai']


def test_resolve_token_user_rejects_token_without_ai_scope(monkeypatch):
    """If `is_valid(['ai'])` returns False, the call must 401."""
    from keel.ai import views as ai_views

    class _FakeAccessToken:
        user = object()
        application = object()
        def is_valid(self, scopes):
            return False  # token doesn't carry the ai scope

    class _FakeValidator:
        def _load_access_token(self, token):
            return _FakeAccessToken()

    monkeypatch.setattr(
        'oauth2_provider.oauth2_validators.OAuth2Validator',
        _FakeValidator,
    )

    class _Req:
        META = {'HTTP_AUTHORIZATION': 'Bearer no-ai-scope'}

    assert ai_views._resolve_token_user(_Req()) == (None, None)
