"""Tests for the Keel-side ``/oauth/ai-key-status/`` peer endpoint.

Contract:
- Peer-client HTTP Basic auth (any confidential OIDC Application) — 401 without.
- 400 when ``sub`` is missing.
- ``ai_key_present`` reflects ``KeelUser.has_anthropic_key()`` for a known sub.
- Unknown / malformed sub → 200 with ``ai_key_present: false`` (no info leak).
"""
import base64
import uuid

import pytest

from keel.accounts.models import KeelUser

pytest.importorskip('cryptography')


def _gen_key():
    from keel.security.encryption import generate_key
    return generate_key()


@pytest.fixture
def app(db):
    from oauth2_provider.models import Application
    return Application.objects.create(
        name='test-product',
        client_id='test-client-id',
        client_secret='test-client-secret',
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris='https://product.example.com/callback/',
    )


def _basic(client_id='test-client-id', secret='test-client-secret'):
    return 'Basic ' + base64.b64encode(f'{client_id}:{secret}'.encode()).decode()


def test_requires_client_auth(db, client):
    resp = client.get('/oauth/ai-key-status/?sub=' + str(uuid.uuid4()))
    assert resp.status_code == 401


def test_bad_secret_rejected(db, client, app):
    resp = client.get(
        '/oauth/ai-key-status/?sub=' + str(uuid.uuid4()),
        HTTP_AUTHORIZATION=_basic(secret='wrong'),
    )
    assert resp.status_code == 401


def test_missing_sub_is_400(db, client, app):
    resp = client.get('/oauth/ai-key-status/', HTTP_AUTHORIZATION=_basic())
    assert resp.status_code == 400


def test_reports_present_true_and_false(db, client, app, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    with_key = KeelUser.objects.create(
        username='haskey', email='haskey@example.test', is_superuser=True,
    )
    with_key.anthropic_api_key = 'sk-ant-test-key-1234567890'
    with_key.save(update_fields=['anthropic_api_key_encrypted'])
    without_key = KeelUser.objects.create(
        username='nokey', email='nokey@example.test', is_superuser=True,
    )

    r1 = client.get(f'/oauth/ai-key-status/?sub={with_key.pk}',
                    HTTP_AUTHORIZATION=_basic())
    assert r1.status_code == 200
    assert r1.json()['ai_key_present'] is True

    r2 = client.get(f'/oauth/ai-key-status/?sub={without_key.pk}',
                    HTTP_AUTHORIZATION=_basic())
    assert r2.status_code == 200
    assert r2.json()['ai_key_present'] is False


def test_unknown_sub_is_false_not_404(db, client, app):
    resp = client.get(f'/oauth/ai-key-status/?sub={uuid.uuid4()}',
                      HTTP_AUTHORIZATION=_basic())
    assert resp.status_code == 200
    assert resp.json()['ai_key_present'] is False


def test_malformed_sub_is_false(db, client, app):
    resp = client.get('/oauth/ai-key-status/?sub=not-a-uuid',
                      HTTP_AUTHORIZATION=_basic())
    assert resp.status_code == 200
    assert resp.json()['ai_key_present'] is False
