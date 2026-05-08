"""Tests that ``KeelOIDCValidator.get_additional_claims`` emits the AI claims.

The scope mapping is covered by ``test_oidc_validator_claim_scope.py``; this
file verifies the actual claim *value* emission. Without these, a refactor
of ``get_additional_claims`` could silently stop emitting the AI claims
while the scope mapping check still passes.
"""

from __future__ import annotations

import pytest

from keel.accounts.models import (
    KeelUser, Organization, OrganizationProductSubscription, ProductAccess,
)


pytest.importorskip('cryptography')
pytest.importorskip('oauth2_provider')


@pytest.fixture
def org(db):
    return Organization.objects.create(slug='oidc-claims-org', name='Test')


@pytest.fixture
def user_with_ai(db, org, settings):
    from keel.security import encryption
    settings.KEEL_ENCRYPTION_KEYS = encryption.generate_key()
    u = KeelUser.objects.create(
        username='oidc-ai-user', email='oidcai@example.test', organization=org,
    )
    OrganizationProductSubscription.objects.create(
        organization=org, product='beacon', is_active=True, ai_enabled=True,
    )
    OrganizationProductSubscription.objects.create(
        organization=org, product='helm', is_active=True, ai_enabled=False,
    )
    ProductAccess.objects.create(
        user=u, product='beacon', role='analyst', is_active=True, ai_enabled=True,
    )
    ProductAccess.objects.create(
        user=u, product='helm', role='helm_admin', is_active=True, ai_enabled=True,
    )
    u.anthropic_api_key = 'sk-ant-test-1234567890abcdef'
    u.save(update_fields=['anthropic_api_key_encrypted'])
    return u


@pytest.fixture
def user_no_key(db, org):
    u = KeelUser.objects.create(
        username='oidc-no-key-user', email='nk@example.test', organization=org,
    )
    OrganizationProductSubscription.objects.get_or_create(
        organization=org, product='beacon',
        defaults={'is_active': True, 'ai_enabled': True},
    )
    ProductAccess.objects.create(
        user=u, product='beacon', role='analyst', is_active=True, ai_enabled=True,
    )
    return u


def _build_oauthlib_request_for(user):
    """Return an oauthlib-shaped request for KeelOIDCValidator.get_additional_claims."""
    class _Req:
        pass
    r = _Req()
    r.user = user
    return r


def test_emits_ai_enabled_products_intersection(db, user_with_ai):
    """`ai_enabled_products` must be the intersection of org-sub × ProductAccess."""
    from keel.oidc.validators import KeelOIDCValidator
    validator = KeelOIDCValidator()

    claims = validator.get_additional_claims(_build_oauthlib_request_for(user_with_ai))

    # Beacon: org has ai_enabled=True, user has ai_enabled=True → included.
    # Helm: org has ai_enabled=False (even though user is True) → excluded.
    assert claims['ai_enabled_products'] == ['beacon']


def test_emits_ai_key_present_true_when_key_set(db, user_with_ai):
    from keel.oidc.validators import KeelOIDCValidator
    validator = KeelOIDCValidator()

    claims = validator.get_additional_claims(_build_oauthlib_request_for(user_with_ai))

    assert claims['ai_key_present'] is True


def test_emits_ai_key_present_false_when_no_key(db, user_no_key):
    from keel.oidc.validators import KeelOIDCValidator
    validator = KeelOIDCValidator()

    claims = validator.get_additional_claims(_build_oauthlib_request_for(user_no_key))

    assert claims['ai_key_present'] is False
    # User has org+product gates open but no key — the products list still
    # reports beacon (key presence is layer 3, not part of this claim).
    assert claims['ai_enabled_products'] == ['beacon']


def test_unauthenticated_request_returns_empty_claims(db):
    """Defense-in-depth: an unauthenticated oauthlib request gets no claims."""
    from keel.oidc.validators import KeelOIDCValidator
    validator = KeelOIDCValidator()

    class _Req:
        user = None

    claims = validator.get_additional_claims(_Req())
    assert claims == {}
