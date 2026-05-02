"""Tests for invitation subscription gating (Layer 2 plan).

Pins the security-critical behaviors:
- The matrix template renders only products in the inviter's org subs.
- ``send_invitation`` rejects POSTs that target unsubscribed products.
- A non-superuser cannot target another org via a tampered POST field.
- ``Invitation.accept`` runs accept-time re-validation against the
  current subscription set (failure mode #4).
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone


@pytest.fixture
def two_orgs(db):
    from keel.accounts.models import Organization, OrganizationProductSubscription

    today = timezone.now().date()
    full = Organization.objects.create(slug='full-org', name='Full Suite Co')
    for code in ('harbor', 'beacon', 'admiralty'):
        OrganizationProductSubscription.objects.create(
            organization=full, product=code, is_active=True, started_at=today,
        )
    bounty = Organization.objects.create(slug='bounty-org', name='Bounty Vendor')
    OrganizationProductSubscription.objects.create(
        organization=bounty, product='bounty', is_active=True, started_at=today,
    )
    return full, bounty


@pytest.fixture
def admin_in_bounty_org(two_orgs):
    """A non-superuser admin whose org subscribes only to Bounty."""
    from keel.accounts.models import KeelUser, ProductAccess

    _full, bounty = two_orgs
    admin = KeelUser.objects.create_user(
        username='vendor-admin', email='admin@vendor.com',
        password='x', organization=bounty,
    )
    ProductAccess.objects.create(
        user=admin, product='bounty', role='admin', is_active=True,
    )
    return admin


# ---------------------------------------------------------------------------
# Accept-time re-validation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_accept_revalidates_against_current_subscriptions(two_orgs):
    """Subscription removed between create and accept → invitation expires."""
    from keel.accounts.models import (
        Invitation, KeelUser, OrganizationProductSubscription,
    )

    full, _bounty = two_orgs
    inv = Invitation.objects.create(
        email='newuser@example.com', product='harbor', role='admin',
        organization=full, expires_at=timezone.now() + timedelta(days=7),
    )
    new_user = KeelUser.objects.create(
        username='newuser', email='newuser@example.com', organization=full,
    )

    # Subscription gets revoked before user clicks the link.
    OrganizationProductSubscription.objects.filter(
        organization=full, product='harbor',
    ).update(is_active=False)

    with pytest.raises(ValueError) as excinfo:
        inv.accept(new_user)
    assert 'no longer subscribed' in str(excinfo.value).lower()

    inv.refresh_from_db()
    assert inv.status == Invitation.Status.EXPIRED
    # No ProductAccess row should have been created.
    assert not new_user.product_access.filter(product='harbor').exists()


@pytest.mark.django_db
def test_accept_succeeds_when_org_still_subscribed(two_orgs):
    from keel.accounts.models import Invitation, KeelUser

    full, _bounty = two_orgs
    inv = Invitation.objects.create(
        email='alice@example.com', product='harbor', role='admin',
        organization=full, expires_at=timezone.now() + timedelta(days=7),
    )
    user = KeelUser.objects.create(
        username='alice', email='alice@example.com', organization=full,
    )
    access = inv.accept(user)
    assert access.product == 'harbor'
    assert access.role == 'admin'
    inv.refresh_from_db()
    assert inv.status == Invitation.Status.ACCEPTED


# ---------------------------------------------------------------------------
# View layer: tampered POST handling
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_send_invitation_drops_unsubscribed_products(client, admin_in_bounty_org):
    """A bounty-org admin POSTing 'harbor' gets that product silently dropped."""
    from keel.accounts.models import Invitation

    client.force_login(admin_in_bounty_org)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'target@example.com',
        'products': ['bounty', 'harbor'],  # harbor is not subscribed
        'role__bounty': 'admin',
        'role__harbor': 'system_admin',
    })
    # Redirects back to the list either way.
    assert response.status_code == 302

    # Only the bounty invitation should exist.
    invs = Invitation.objects.filter(email='target@example.com')
    assert list(invs.values_list('product', flat=True)) == ['bounty']
    assert invs.first().organization_id == admin_in_bounty_org.organization_id


@pytest.mark.django_db
def test_non_superuser_cannot_target_other_org_via_post(client, admin_in_bounty_org, two_orgs):
    """The 'organization' POST field is ignored for non-superusers."""
    from keel.accounts.models import Invitation

    full, _bounty = two_orgs
    client.force_login(admin_in_bounty_org)
    client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'crossorg@example.com',
        'products': ['bounty'],
        'role__bounty': 'admin',
        # Tampered: non-superuser tries to switch to the other org.
        'organization': str(full.pk),
    })
    inv = Invitation.objects.get(email='crossorg@example.com')
    # Server-side derivation MUST have ignored the POST field.
    assert inv.organization_id == admin_in_bounty_org.organization_id
    assert inv.organization_id != full.pk


@pytest.mark.django_db
def test_invitation_list_renders_only_subscribed_products(client, admin_in_bounty_org):
    """The view layer filters the matrix to subscribed products only.

    Asserts on response.context rather than rendered HTML so the test
    is independent of the staticfiles manifest (which isn't built in
    the test environment).
    """
    from django.test import override_settings

    client.force_login(admin_in_bounty_org)
    # Disable manifest hashing for the render path; the matrix logic
    # happens in the view, not the template.
    with override_settings(
        STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        },
    ):
        response = client.get(reverse('keel_accounts:invitation_list'))
    assert response.status_code == 200

    # The view's products context is the filtered list of (code, label)
    # tuples for products the inviter's org actively subscribes to.
    matrix_codes = {code for code, _label in response.context['products']}
    assert 'bounty' in matrix_codes
    assert 'harbor' not in matrix_codes
    assert 'beacon' not in matrix_codes


# ---------------------------------------------------------------------------
# KeelUser.save org-change reconciliation hook
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_save_hook_reconciles_on_org_change(two_orgs):
    """Reassigning a user's org cascades to ProductAccess deactivation."""
    from keel.accounts.models import KeelUser, ProductAccess

    full, bounty = two_orgs
    user = KeelUser.objects.create(
        username='movealong', email='m@x.com', organization=full,
    )
    ProductAccess.objects.create(user=user, product='harbor', role='admin')
    ProductAccess.objects.create(user=user, product='beacon', role='analyst')

    # Move via the save() path (not raw UPDATE) — the save hook should
    # detect the org change and call reconcile_user_product_access.
    user.organization = bounty
    user.save()

    # Both ProductAccess rows should now be inactive (bounty doesn't
    # subscribe to harbor or beacon).
    assert not ProductAccess.objects.filter(
        user=user, is_active=True,
    ).exists()
