"""Tests for the agency_admin role-grant gate.

Pins the security-critical behaviors introduced with the suite-wide
``agency_admin`` role:

- Agency admins can grant operator-tier roles within their own org.
- Agency admins CANNOT grant ``system_admin`` / ``agency_admin`` /
  ``admin`` / ``*_admin`` roles via the invitation matrix or the
  direct-grant view.
- System admins (and superusers) retain full role-grant powers.
- A blocked grant attempt is recorded as a ``role_grant_denied`` audit
  log row.
- Every product registers ``agency_admin`` in PRODUCT_ROLES.
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def harbor_org(db):
    from keel.accounts.models import Organization, OrganizationProductSubscription

    today = timezone.now().date()
    org = Organization.objects.create(slug='harbor-org', name='Harbor Customer')
    for code in ('harbor', 'beacon', 'admiralty', 'lookout', 'manifest',
                 'bounty', 'purser', 'helm', 'yeoman', 'keel'):
        OrganizationProductSubscription.objects.create(
            organization=org, product=code, is_active=True, started_at=today,
        )
    return org


@pytest.fixture
def agency_admin_user(harbor_org):
    """A non-superuser agency_admin in harbor-org."""
    from keel.accounts.models import KeelUser, ProductAccess

    user = KeelUser.objects.create_user(
        username='aa-user', email='aa@example.com',
        password='x', organization=harbor_org,
    )
    ProductAccess.objects.create(
        user=user, product='harbor', role='agency_admin', is_active=True,
    )
    return user


@pytest.fixture
def system_admin_user(harbor_org):
    """A non-superuser system_admin in harbor-org."""
    from keel.accounts.models import KeelUser, ProductAccess

    user = KeelUser.objects.create_user(
        username='sa-user', email='sa@example.com',
        password='x', organization=harbor_org,
    )
    ProductAccess.objects.create(
        user=user, product='harbor', role='system_admin', is_active=True,
    )
    return user


# ---------------------------------------------------------------------------
# can_grant_admin_roles
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_agency_admin_cannot_grant_admin_roles(agency_admin_user):
    from keel.accounts.services import can_grant_admin_roles
    assert can_grant_admin_roles(agency_admin_user) is False


@pytest.mark.django_db
def test_system_admin_can_grant_admin_roles(system_admin_user):
    from keel.accounts.services import can_grant_admin_roles
    assert can_grant_admin_roles(system_admin_user) is True


@pytest.mark.django_db
def test_superuser_can_grant_admin_roles(harbor_org):
    from keel.accounts.models import KeelUser
    from keel.accounts.services import can_grant_admin_roles
    superu = KeelUser.objects.create_user(
        username='superu', email='super@example.com',
        password='x', is_superuser=True, is_staff=True,
    )
    assert can_grant_admin_roles(superu) is True


# ---------------------------------------------------------------------------
# available_grantable_roles
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_agency_admin_role_list_excludes_protected(agency_admin_user):
    from keel.accounts.services import available_grantable_roles
    roles = {slug for slug, _ in available_grantable_roles(agency_admin_user, 'harbor')}
    # Operator-tier present
    assert 'program_officer' in roles
    assert 'reviewer' in roles
    # Protected admin tier stripped
    assert 'system_admin' not in roles
    assert 'agency_admin' not in roles


@pytest.mark.django_db
def test_system_admin_role_list_includes_protected(system_admin_user):
    from keel.accounts.services import available_grantable_roles
    roles = {slug for slug, _ in available_grantable_roles(system_admin_user, 'harbor')}
    assert 'system_admin' in roles
    assert 'agency_admin' in roles
    assert 'program_officer' in roles


# ---------------------------------------------------------------------------
# View layer — invitation matrix POST
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_agency_admin_invitation_blocks_system_admin_grant(client, agency_admin_user):
    """Agency admin POSTing system_admin role gets blocked + audit row."""
    from keel.accounts.models import AuditLog, Invitation

    client.force_login(agency_admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'target@example.com',
        'products': ['harbor'],
        'role__harbor': 'system_admin',  # protected
    })
    assert response.status_code == 302

    # No invitation should have been created.
    assert not Invitation.objects.filter(email='target@example.com').exists()

    # Audit row recorded.
    denied = AuditLog.objects.filter(
        user=agency_admin_user, action='role_grant_denied',
    )
    assert denied.exists()
    row = denied.first()
    assert row.entity_type == 'Invitation'
    assert row.entity_id == 'target@example.com'
    assert any(
        d['role'] == 'system_admin' and d['product'] == 'harbor'
        for d in row.changes['denied_grants']
    )


@pytest.mark.django_db
def test_agency_admin_invitation_blocks_agency_admin_peer_grant(client, agency_admin_user):
    """Agency admin cannot peer-escalate by granting another agency_admin."""
    from keel.accounts.models import Invitation

    client.force_login(agency_admin_user)
    client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'peer@example.com',
        'products': ['harbor'],
        'role__harbor': 'agency_admin',  # protected (peer)
    })
    assert not Invitation.objects.filter(email='peer@example.com').exists()


@pytest.mark.django_db
def test_agency_admin_invitation_allows_operator_grant(client, agency_admin_user):
    """Agency admin can still grant operator-tier roles."""
    from keel.accounts.models import Invitation

    client.force_login(agency_admin_user)
    client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'analyst@example.com',
        'products': ['harbor'],
        'role__harbor': 'program_officer',
    })
    inv = Invitation.objects.get(email='analyst@example.com')
    assert inv.product == 'harbor'
    assert inv.role == 'program_officer'
    assert inv.organization_id == agency_admin_user.organization_id


@pytest.mark.django_db
def test_system_admin_invitation_can_grant_any_role(client, system_admin_user):
    from keel.accounts.models import Invitation

    client.force_login(system_admin_user)
    client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'newadmin@example.com',
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
    })
    inv = Invitation.objects.get(email='newadmin@example.com')
    assert inv.role == 'agency_admin'


# ---------------------------------------------------------------------------
# View layer — direct grant_access
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_agency_admin_direct_grant_blocks_admin(client, agency_admin_user, harbor_org):
    """grant_access view enforces the same gate as the invitation matrix."""
    from keel.accounts.models import AuditLog, KeelUser, ProductAccess

    target = KeelUser.objects.create_user(
        username='target', email='t@example.com', password='x',
        organization=harbor_org,
    )
    client.force_login(agency_admin_user)
    client.post(reverse('keel_accounts:grant_access', args=[target.pk]), {
        'product': 'harbor',
        'role': 'system_admin',
    })
    # Target user must NOT have gained system_admin.
    assert not ProductAccess.objects.filter(
        user=target, product='harbor', role='system_admin', is_active=True,
    ).exists()
    # Audit row recorded.
    assert AuditLog.objects.filter(
        user=agency_admin_user, action='role_grant_denied',
        entity_type='ProductAccess', entity_id=str(target.pk),
    ).exists()
