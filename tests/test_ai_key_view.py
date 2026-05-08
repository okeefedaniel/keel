"""End-to-end tests for ``GET /api/v1/ai/key/``.

The view is the security-sensitive primitive: products call it with
the user's OIDC bearer token to fetch the cleartext Anthropic key.
The unit tests in ``test_ai_key_fetch_security.py`` cover the token
lookup helper and the no-redirect opener; this file exercises the
assembled view via Django's test client so the wiring is verified
end-to-end.

Status code contract:
- 200 — key available, returned in body with masked hint
- 401 — bearer missing/invalid/expired/wrong scope
- 404 — token valid but user has no key set
- 429 — per-user rate limit tripped
"""

from __future__ import annotations

import json

import pytest
from django.test import RequestFactory
from django.urls import reverse


pytest.importorskip('cryptography')


@pytest.fixture
def factory():
    return RequestFactory()


@pytest.fixture
def user_with_key(db, settings):
    from keel.accounts.models import KeelUser, Organization
    from keel.security import encryption
    settings.KEEL_ENCRYPTION_KEYS = encryption.generate_key()
    org = Organization.objects.create(slug='ai-key-view-org', name='Test')
    u = KeelUser.objects.create(
        username='ai-key-view-user', email='aikv@example.test',
        organization=org,
    )
    u.anthropic_api_key = 'sk-ant-test-FAKE-1234567890abcdef-XYZ9'
    u.save(update_fields=['anthropic_api_key_encrypted'])
    return u


@pytest.fixture
def user_without_key(db, settings):
    from keel.accounts.models import KeelUser, Organization
    from keel.security import encryption
    settings.KEEL_ENCRYPTION_KEYS = encryption.generate_key()
    org = Organization.objects.create(slug='ai-key-view-org-2', name='Test 2')
    return KeelUser.objects.create(
        username='no-key-user', email='nokey@example.test', organization=org,
    )


def _stub_token_validator(monkeypatch, *, user, scopes=('ai',), client_id='test-client'):
    """Bypass real bearer auth by stubbing OAuth2Validator._load_access_token."""
    from oauth2_provider import oauth2_validators as oauth2_validators_mod

    class _FakeAccessToken:
        def __init__(self, u, sc, cid):
            self.user = u
            self.application = type('A', (), {'client_id': cid})()
            self._scopes = list(sc)

        def is_valid(self, requested):
            return all(s in self._scopes for s in requested)

    class _FakeValidator:
        def _load_access_token(self, token):
            return _FakeAccessToken(user, scopes, client_id)

    monkeypatch.setattr(
        oauth2_validators_mod, 'OAuth2Validator', _FakeValidator,
    )


def test_200_returns_cleartext_key_and_hint(db, factory, user_with_key, monkeypatch):
    _stub_token_validator(monkeypatch, user=user_with_key)
    from keel.ai.views import ai_key_view

    req = factory.get('/api/v1/ai/key/', HTTP_AUTHORIZATION='Bearer faketoken')
    resp = ai_key_view(req)

    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert body['key'] == 'sk-ant-test-FAKE-1234567890abcdef-XYZ9'
    assert body['hint'].endswith('XYZ9')
    assert 'sk-ant' not in body['hint']  # hint masks everything but last-4
    assert body['expires_in'] == 60
    # Cache-Control headers must prevent any layer from caching the response.
    assert 'no-store' in resp['Cache-Control']
    assert resp['Pragma'] == 'no-cache'


def test_404_when_user_has_no_key(db, factory, user_without_key, monkeypatch):
    _stub_token_validator(monkeypatch, user=user_without_key)
    from keel.ai.views import ai_key_view

    req = factory.get('/api/v1/ai/key/', HTTP_AUTHORIZATION='Bearer faketoken')
    resp = ai_key_view(req)

    assert resp.status_code == 404
    body = json.loads(resp.content)
    assert body['error'] == 'no_key_configured'


def test_401_when_no_bearer_header(db, factory):
    from keel.ai.views import ai_key_view

    req = factory.get('/api/v1/ai/key/')
    resp = ai_key_view(req)

    assert resp.status_code == 401
    assert json.loads(resp.content)['error'] == 'invalid_token'


def test_401_when_token_lacks_ai_scope(db, factory, user_with_key, monkeypatch):
    # Token has `product_access` and `email` but not `ai`.
    _stub_token_validator(
        monkeypatch, user=user_with_key, scopes=('product_access', 'email'),
    )
    from keel.ai.views import ai_key_view

    req = factory.get('/api/v1/ai/key/', HTTP_AUTHORIZATION='Bearer faketoken')
    resp = ai_key_view(req)

    assert resp.status_code == 401


def test_429_when_rate_limit_tripped(db, factory, user_with_key, monkeypatch):
    _stub_token_validator(monkeypatch, user=user_with_key)
    from keel.ai import views as ai_views

    # Force the rate-limit helper to deny.
    monkeypatch.setattr(ai_views, '_rate_limit', lambda user_id: False)

    req = factory.get('/api/v1/ai/key/', HTTP_AUTHORIZATION='Bearer faketoken')
    resp = ai_views.ai_key_view(req)

    assert resp.status_code == 429
    assert json.loads(resp.content)['error'] == 'rate_limited'


def test_audit_log_written_on_success(db, factory, user_with_key, monkeypatch):
    _stub_token_validator(
        monkeypatch, user=user_with_key, client_id='beacon-client',
    )
    from keel.ai.views import ai_key_view
    from keel.accounts.models import AuditLog

    req = factory.get('/api/v1/ai/key/', HTTP_AUTHORIZATION='Bearer faketoken')
    resp = ai_key_view(req)
    assert resp.status_code == 200

    rows = list(AuditLog.objects.filter(action='ai_key_fetch'))
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == user_with_key.pk
    assert row.changes['client_id'] == 'beacon-client'
    assert row.changes['success'] is True
    # Plaintext key MUST NOT appear in the audit log — only the masked hint.
    assert 'sk-ant-test-FAKE-1234567890abcdef-XYZ9' not in row.description
    assert 'sk-ant-test-FAKE-1234567890abcdef-XYZ9' not in json.dumps(row.changes)


def test_audit_log_written_on_404(db, factory, user_without_key, monkeypatch):
    _stub_token_validator(monkeypatch, user=user_without_key)
    from keel.ai.views import ai_key_view
    from keel.accounts.models import AuditLog

    req = factory.get('/api/v1/ai/key/', HTTP_AUTHORIZATION='Bearer faketoken')
    ai_key_view(req)

    rows = list(AuditLog.objects.filter(action='ai_key_fetch'))
    assert len(rows) == 1
    assert rows[0].changes['success'] is False
    assert rows[0].changes['hint'] == 'no_key'
