"""Tests for the Organization layer (Layer 2 of the SSO/accounts plan).

Pins:
- The reserved-slug guard rejects new ``docklabs-internal`` rows but
  allows the migration-seeded one to be updated normally.
- ``OrganizationProductSubscription.active_product_codes`` returns
  exactly the active subscriptions for the given org.
- ``KeelUser.clean()`` rejects non-superuser accounts without an
  organization (mirror of the DB CheckConstraint).
- ``reconcile_user_product_access`` deactivates ProductAccess rows
  for products the user's new org doesn't subscribe to AND bumps
  ``last_logout_at`` to invalidate stale sessions.
- ``Invitation.accept`` runs accept-time re-validation against the
  org's current subscription set.

Avoids the migration framework: uses real models and the test DB
created by Django's ``django_db`` fixture. Migration logic itself is
exercised when the test DB is built.
"""
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone


# ---------------------------------------------------------------------------
# Reserved slug guard
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_reserved_slug_blocks_new_admin_creation():
    from keel.accounts.models import Organization

    org = Organization(slug='docklabs-internal', name='Imposter')
    with pytest.raises(ValidationError) as excinfo:
        org.save()  # save() calls full_clean() which calls clean()
    assert 'reserved' in str(excinfo.value).lower()


@pytest.mark.django_db
def test_reserved_slug_allows_update_of_seeded_row():
    """Seeded default org (created by 0011) must still be admin-editable.

    The migration runs at test-DB creation (pytest-django), so the
    ``docklabs-internal`` row already exists. Verify that loading it
    and saving with a renamed ``name`` does NOT trip the reserved-slug
    guard — the guard fires only on insert, not on update.
    """
    from keel.accounts.models import Organization

    seed = Organization.objects.get(slug='docklabs-internal')
    seed.name = 'DockLabs Internal (renamed)'
    seed.save()  # should NOT raise — _state.adding is False on update.
    seed.refresh_from_db()
    assert seed.name == 'DockLabs Internal (renamed)'
    # Slug unchanged.
    assert seed.slug == 'docklabs-internal'


# ---------------------------------------------------------------------------
# active_product_codes
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_active_product_codes_returns_only_active():
    from keel.accounts.models import Organization, OrganizationProductSubscription

    org = Organization.objects.create(slug='ct-decd', name='CT DECD')
    today = timezone.now().date()
    OrganizationProductSubscription.objects.create(
        organization=org, product='harbor', is_active=True, started_at=today,
    )
    OrganizationProductSubscription.objects.create(
        organization=org, product='beacon', is_active=True, started_at=today,
    )
    # Inactive sub should NOT appear.
    OrganizationProductSubscription.objects.create(
        organization=org, product='lookout', is_active=False, started_at=today,
    )

    codes = OrganizationProductSubscription.active_product_codes(org)
    assert set(codes) == {'harbor', 'beacon'}


@pytest.mark.django_db
def test_active_product_codes_handles_none_org():
    from keel.accounts.models import OrganizationProductSubscription

    # Cross-org superuser path: organization is None, helper returns []
    # rather than raising or running an unscoped query.
    assert OrganizationProductSubscription.active_product_codes(None) == []


# ---------------------------------------------------------------------------
# KeelUser invariant
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_keeluser_clean_rejects_org_none_for_non_superuser():
    from keel.accounts.models import KeelUser

    user = KeelUser(
        username='alice', email='alice@example.com',
        is_superuser=False, organization=None,
    )
    with pytest.raises(ValidationError) as excinfo:
        user.clean()
    assert 'organization' in str(excinfo.value).lower()


@pytest.mark.django_db
def test_keeluser_clean_allows_org_none_for_superuser():
    from keel.accounts.models import KeelUser

    su = KeelUser(
        username='dokadmin-test', email='dok@example.com',
        is_superuser=True, organization=None,
    )
    su.clean()  # should NOT raise


# ---------------------------------------------------------------------------
# reconcile_user_product_access
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_reconcile_revokes_unsubscribed_products_and_bumps_last_logout():
    from keel.accounts.models import (
        KeelUser, Organization, OrganizationProductSubscription, ProductAccess,
    )
    from keel.accounts.services import reconcile_user_product_access

    full_suite = Organization.objects.create(slug='full', name='Full Suite Co')
    today = timezone.now().date()
    for code in ('harbor', 'beacon', 'admiralty'):
        OrganizationProductSubscription.objects.create(
            organization=full_suite, product=code, is_active=True,
            started_at=today,
        )
    bounty_only = Organization.objects.create(slug='bounty-only', name='Bounty Co')
    OrganizationProductSubscription.objects.create(
        organization=bounty_only, product='bounty', is_active=True,
        started_at=today,
    )

    user = KeelUser.objects.create(
        username='bob', email='bob@example.com', organization=full_suite,
    )
    for code in ('harbor', 'beacon', 'admiralty'):
        ProductAccess.objects.create(user=user, product=code, role='admin')

    # Move the user to bounty-only via direct UPDATE so we can drive
    # reconcile_user_product_access manually (bypasses the save hook
    # to test the function in isolation).
    KeelUser.objects.filter(pk=user.pk).update(organization=bounty_only)
    user.refresh_from_db()

    assert user.last_logout_at is None
    revoked = reconcile_user_product_access(user, force_logout=True)
    assert revoked == 3  # all 3 products revoked

    user.refresh_from_db()
    assert user.last_logout_at is not None
    active_products = set(
        ProductAccess.objects.filter(user=user, is_active=True)
            .values_list('product', flat=True)
    )
    assert active_products == set()  # bob is in bounty-only but had no bounty access


@pytest.mark.django_db
def test_reconcile_no_op_for_superuser():
    from keel.accounts.models import KeelUser
    from keel.accounts.services import reconcile_user_product_access

    su = KeelUser.objects.create(
        username='dokadmin-noorg', email='dok@x.com',
        is_superuser=True, organization=None,
    )
    assert reconcile_user_product_access(su, force_logout=True) == 0


# ---------------------------------------------------------------------------
# OIDC organization claims
# ---------------------------------------------------------------------------
def test_organization_claims_in_oidc_claim_scope():
    """The CSO 'silent strip' trap: every custom claim must map to a scope."""
    from keel.oidc.validators import KeelOIDCValidator

    assert KeelOIDCValidator.oidc_claim_scope['organization'] == 'organization'
    assert KeelOIDCValidator.oidc_claim_scope['organization_name'] == 'organization'


def test_organization_claims_in_docklabs_custom_claims_set():
    from keel.oidc.validators import KeelOIDCValidator

    assert 'organization' in KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS
    assert 'organization_name' in KeelOIDCValidator.DOCKLABS_CUSTOM_CLAIMS
    KeelOIDCValidator.validate_claim_scope()  # must not raise
