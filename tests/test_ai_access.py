"""Tests for the three-layer AI gating helpers in ``keel.core.ai_access``.

The contract under test:

- ``user_can_use_ai`` returns True iff (org-sub.ai_enabled AND
  product-access.ai_enabled AND user.has_anthropic_key()).
- ``user_ai_state`` collapses the 8-cell truth table into one of
  {'off', 'needs_key', 'ready'}.
- ``ai_enabled_products_for_user`` returns the intersection of
  org-sub and per-user flags (independent of key presence).
- Superusers (dokadmin) bypass org-sub but not per-user or key.
"""

import pytest
from django.test import override_settings

from keel.accounts.models import (
    KeelUser, Organization, OrganizationProductSubscription,
    ProductAccess,
)
from keel.core.ai_access import (
    ai_enabled_products_for_user, user_ai_state, user_can_use_ai,
)


pytest.importorskip('cryptography')


@pytest.fixture
def org(db):
    return Organization.objects.create(slug='acme-test', name='Acme Test')


@pytest.fixture
def user(db, org, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    return KeelUser.objects.create(
        username='alice-ai-test',
        email='alice@example.test',
        organization=org,
    )


def _gen_key():
    from keel.security.encryption import generate_key
    return generate_key()


def _set_org_ai(org, product, enabled):
    OrganizationProductSubscription.objects.update_or_create(
        organization=org, product=product,
        defaults={'is_active': True, 'ai_enabled': enabled},
    )


def _set_user_ai(user, product, enabled):
    ProductAccess.objects.update_or_create(
        user=user, product=product,
        defaults={'role': 'analyst', 'is_active': True, 'ai_enabled': enabled},
    )


def test_all_three_layers_pass_returns_ready(db, user, org, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    _set_org_ai(org, 'beacon', True)
    _set_user_ai(user, 'beacon', True)
    user.anthropic_api_key = 'sk-ant-test-key-12345678901234567890'
    user.save(update_fields=['anthropic_api_key_encrypted'])

    assert user_can_use_ai(user, 'beacon') is True
    assert user_ai_state(user, 'beacon') == 'ready'


def test_org_off_returns_off(db, user, org, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    _set_org_ai(org, 'beacon', False)
    _set_user_ai(user, 'beacon', True)
    user.anthropic_api_key = 'sk-ant-test-key-12345678901234567890'
    user.save(update_fields=['anthropic_api_key_encrypted'])

    assert user_can_use_ai(user, 'beacon') is False
    assert user_ai_state(user, 'beacon') == 'off'


def test_user_off_returns_off(db, user, org, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    _set_org_ai(org, 'beacon', True)
    _set_user_ai(user, 'beacon', False)
    user.anthropic_api_key = 'sk-ant-test-key-12345678901234567890'
    user.save(update_fields=['anthropic_api_key_encrypted'])

    assert user_can_use_ai(user, 'beacon') is False
    assert user_ai_state(user, 'beacon') == 'off'


def test_visibility_pass_but_no_key_returns_needs_key(db, user, org, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    _set_org_ai(org, 'beacon', True)
    _set_user_ai(user, 'beacon', True)
    # No key set.

    assert user_can_use_ai(user, 'beacon') is False
    assert user_ai_state(user, 'beacon') == 'needs_key'


def test_anonymous_user_returns_off(db):
    from django.contrib.auth.models import AnonymousUser
    anon = AnonymousUser()
    assert user_can_use_ai(anon, 'beacon') is False
    assert user_ai_state(anon, 'beacon') == 'off'


def test_ai_enabled_products_intersects_layers(db, user, org, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    _set_org_ai(org, 'beacon', True)
    _set_org_ai(org, 'bounty', True)
    _set_org_ai(org, 'helm', False)  # org disabled — should drop out
    _set_user_ai(user, 'beacon', True)
    _set_user_ai(user, 'bounty', False)  # user disabled — should drop out
    _set_user_ai(user, 'helm', True)
    # No key set — list should still include AI-eligible products,
    # since key presence is layer 3 (separate claim).

    products = ai_enabled_products_for_user(user)
    assert products == ['beacon']


def test_superuser_bypasses_org_sub_layer(db, settings):
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    su = KeelUser.objects.create(
        username='super-ai-test', email='super@example.test',
        is_superuser=True, is_staff=True,
    )
    # No org-sub row at all. Superuser should still pass layer 1 and
    # layer 2 (no ProductAccess required either). Still fails layer 3
    # since no key is set.
    assert user_ai_state(su, 'beacon') == 'needs_key'
    su.anthropic_api_key = 'sk-ant-test-key-12345678901234567890'
    su.save(update_fields=['anthropic_api_key_encrypted'])
    assert user_ai_state(su, 'beacon') == 'ready'
