"""Tests for the AI-flag tampering filter in ``send_invitation``.

Eng-review test gap #3. The invite matrix template only renders the
AI checkbox for products where the inviting org has ``ai_enabled=True``.
A forged POST that includes ``ai_enabled__beacon=1`` for a product the
org doesn't have AI on must be silently dropped server-side, mirroring
the existing subscription-tamper filter.
"""

from __future__ import annotations

import pytest

from keel.accounts.models import (
    Invitation, KeelUser, Organization, OrganizationProductSubscription,
)


pytest.importorskip('cryptography')


@pytest.fixture
def admin_user(db):
    org = Organization.objects.create(slug='invite-test-org', name='Inv Test')
    OrganizationProductSubscription.objects.create(
        organization=org, product='beacon', is_active=True, ai_enabled=True,
    )
    OrganizationProductSubscription.objects.create(
        organization=org, product='bounty', is_active=True, ai_enabled=False,
    )
    u = KeelUser.objects.create(
        username='inviter', email='inviter@example.test', organization=org,
        is_staff=True, is_superuser=True,
    )
    return u


@pytest.fixture
def client(admin_user):
    from django.test import Client
    c = Client()
    c.force_login(admin_user)
    return c


def test_ai_flag_honored_when_org_has_ai_on_product(db, client, admin_user):
    resp = client.post('/keel/accounts/invitations/send/', {
        'email': 'recipient@example.test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
        'ai_enabled__beacon': '1',
    })
    assert resp.status_code in (200, 302)

    inv = Invitation.objects.filter(email='recipient@example.test', product='beacon').first()
    assert inv is not None
    assert inv.ai_enabled is True


def test_ai_flag_dropped_when_org_lacks_ai_on_product(db, client, admin_user):
    """Forge a POST with `ai_enabled__bounty=1` even though bounty has ai_enabled=False on the org-sub."""
    resp = client.post('/keel/accounts/invitations/send/', {
        'email': 'tamper-recipient@example.test',
        'products': ['bounty'],
        'role__bounty': 'analyst',
        'ai_enabled__bounty': '1',  # Tampered — org doesn't have AI on bounty.
    })
    assert resp.status_code in (200, 302)

    inv = Invitation.objects.filter(
        email='tamper-recipient@example.test', product='bounty',
    ).first()
    assert inv is not None
    # Tampered flag must be silently dropped to False.
    assert inv.ai_enabled is False


def test_ai_flag_defaults_false_when_not_posted(db, client, admin_user):
    """Omitting the AI checkbox in the POST means False on the resulting Invitation."""
    resp = client.post('/keel/accounts/invitations/send/', {
        'email': 'nochk-recipient@example.test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
        # No ai_enabled__beacon field at all.
    })
    assert resp.status_code in (200, 302)

    inv = Invitation.objects.filter(
        email='nochk-recipient@example.test', product='beacon',
    ).first()
    assert inv is not None
    assert inv.ai_enabled is False


def test_invite_accept_propagates_ai_flag_to_product_access(db, admin_user):
    """End-to-end: Invitation.accept() carries ai_enabled into ProductAccess."""
    from django.utils import timezone
    from datetime import timedelta

    from keel.accounts.models import ProductAccess

    org = admin_user.organization
    inv = Invitation.objects.create(
        email='accept@example.test',
        product='beacon',
        role='analyst',
        ai_enabled=True,
        organization=org,
        invited_by=admin_user,
        expires_at=timezone.now() + timedelta(days=7),
    )

    new_user = KeelUser.objects.create(
        username='accept-user', email='accept@example.test', organization=org,
    )
    inv.accept(new_user)

    access = ProductAccess.objects.get(user=new_user, product='beacon')
    assert access.ai_enabled is True
    assert access.role == 'analyst'
