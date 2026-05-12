"""Boot-time invariant: every SYNCED_FIELDS entry is wired end-to-end.

``keel.accounts.models.SYNCED_FIELDS`` is the single source of truth
for which ``ProductAccess`` fields cross the OIDC boundary. Three
places must stay in agreement:

  1. The registry itself (here).
  2. ``KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS`` registers the claim
     and ``oidc_claim_scope`` gates it on a scope.
  3. The SSO adapter's ``_mirror_product_access`` writes the field
     back to the local ``ProductAccess`` row.

This test pins the invariant: if anyone adds a field to the registry
without wiring (2) or (3), the boot check raises and this test fails
with a message naming the gap. The matching failure mode that shipped
in production was ``is_beta_tester`` reaching the model and
``Invitation.accept`` but none of the three OIDC boundary spots, so
the flag had no observable effect on any product for months.
"""
from __future__ import annotations

import pytest


pytest.importorskip('oauth2_provider')


def test_every_synced_field_has_claim_and_scope():
    from keel.accounts.models import SYNCED_FIELDS, ProductAccess
    from keel.oidc.validators import KeelOIDCValidator

    for sf in SYNCED_FIELDS:
        # (1) field actually exists on ProductAccess
        ProductAccess._meta.get_field(sf.field)
        # (2a) claim registered
        assert sf.claim in KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS, (
            f'SYNCED_FIELDS {sf.field!r} → claim {sf.claim!r} is missing '
            f'from KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS'
        )
        # (2b) claim scoped
        assert sf.claim in KeelOIDCValidator.oidc_claim_scope, (
            f'SYNCED_FIELDS {sf.field!r} → claim {sf.claim!r} is missing '
            f'from KeelOIDCValidator.oidc_claim_scope (django-oauth-toolkit '
            f'will silently strip it from every token)'
        )


def test_validate_claim_scope_passes_with_default_registry():
    """``KeelOIDCValidator.validate_claim_scope`` runs at boot."""
    from keel.oidc.validators import KeelOIDCValidator
    KeelOIDCValidator.validate_claim_scope()  # must not raise


def test_validate_claim_scope_raises_on_unwired_synced_field(monkeypatch):
    """Add a deliberately-wrong field and confirm the boot check catches it."""
    from django.core.exceptions import ImproperlyConfigured
    from keel.accounts import models as accounts_models
    from keel.oidc.validators import KeelOIDCValidator

    bogus = accounts_models.SyncedField(
        'is_active', 'definitely_not_wired_claim', 'list',
    )
    monkeypatch.setattr(
        accounts_models, 'SYNCED_FIELDS',
        accounts_models.SYNCED_FIELDS + (bogus,),
    )

    with pytest.raises(ImproperlyConfigured) as excinfo:
        KeelOIDCValidator.validate_claim_scope()

    msg = str(excinfo.value)
    assert 'definitely_not_wired_claim' in msg
    assert 'is_active' in msg


def test_mirror_synced_fields_returns_defaults_for_each_code():
    """The adapter helper produces an ``update_or_create`` ``defaults`` dict."""
    from keel.accounts.models import mirror_synced_fields

    claims = {
        'product_access': {'beacon': 'analyst', 'harbor': 'admin'},
        'beta_products': ['beacon'],
        'ai_enabled_products': ['harbor'],
    }
    out = mirror_synced_fields(claims)

    assert set(out.keys()) == {'beacon', 'harbor'}

    assert out['beacon']['role'] == 'analyst'
    assert out['beacon']['is_active'] is True
    assert out['beacon']['is_beta_tester'] is True
    assert out['beacon']['ai_enabled'] is False

    assert out['harbor']['role'] == 'admin'
    assert out['harbor']['is_active'] is True
    assert out['harbor']['is_beta_tester'] is False
    assert out['harbor']['ai_enabled'] is True


def test_mirror_synced_fields_writes_every_registered_field():
    """Every SYNCED_FIELDS entry MUST contribute to the mirror output.

    This pins the second half of the invariant: a field declared in the
    registry but accidentally dropped from the mirror translator would
    leave the local row stale even though the IdP emits the claim.
    """
    from keel.accounts.models import SYNCED_FIELDS, mirror_synced_fields

    claims = {
        'product_access': {'beacon': 'analyst'},
        'beta_products': ['beacon'],
        'ai_enabled_products': ['beacon'],
    }
    out = mirror_synced_fields(claims)['beacon']
    for sf in SYNCED_FIELDS:
        assert sf.field in out, (
            f'mirror_synced_fields dropped {sf.field!r} — local '
            f'ProductAccess row will go stale on every login'
        )


def test_mirror_synced_fields_tolerates_missing_claim():
    """An OIDC token from an older Keel that doesn't emit a field must
    not blow up the adapter — the field simply isn't written, and the
    existing local row value is preserved by ``update_or_create``.
    """
    from keel.accounts.models import mirror_synced_fields

    # Only the role claim is present; beta + ai claims absent.
    claims = {'product_access': {'beacon': 'analyst'}}
    out = mirror_synced_fields(claims)
    assert out['beacon']['role'] == 'analyst'
    assert 'is_beta_tester' not in out['beacon']
    assert 'ai_enabled' not in out['beacon']
