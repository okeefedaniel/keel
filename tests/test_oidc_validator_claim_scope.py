"""Tests for ``KeelOIDCValidator.validate_claim_scope``.

Every DockLabs custom claim must be wired into ``oidc_claim_scope`` so
django-oauth-toolkit does not silently strip it from issued ID tokens.
This test pins that invariant — the exact failure mode that shipped
broken ``product_access`` tokens to Harbor last quarter.
"""
import pytest


def test_validate_claim_scope_passes_for_default_mapping():
    from keel.oidc.validators import KeelOIDCValidator  # noqa: triggers lazy build

    # Should not raise — every DOCKLABS_CUSTOM_CLAIMS entry is mapped.
    KeelOIDCValidator.validate_claim_scope()


def test_validate_claim_scope_raises_when_claim_unscoped():
    from django.core.exceptions import ImproperlyConfigured
    from keel.oidc.validators import KeelOIDCValidator

    # Simulate drift: add a new custom claim without scope mapping.
    original = KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS
    KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS = frozenset(
        set(original) | {'unmapped_claim'}
    )
    try:
        with pytest.raises(ImproperlyConfigured) as excinfo:
            KeelOIDCValidator.validate_claim_scope()
        assert 'unmapped_claim' in str(excinfo.value)
    finally:
        KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS = original


def test_product_access_claim_mapped_to_product_access_scope():
    from keel.oidc.validators import KeelOIDCValidator

    assert KeelOIDCValidator.oidc_claim_scope['product_access'] == 'product_access'
    assert KeelOIDCValidator.oidc_claim_scope['is_state_user'] == 'product_access'
    assert KeelOIDCValidator.oidc_claim_scope['agency_abbr'] == 'product_access'
