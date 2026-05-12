"""Tests for keel_site.audit.permissions.

Covers the security-critical surfaces flagged in the autoplan eng review:
- agency_admin scope is per-product (no cross-product PII leak)
- visible_products_for intersects with KEEL_FLEET_PRODUCTS (no stale-role leak)
- 'keel' is only auto-included for superusers
- can_view_audit honors superuser OR system_admin OR agency_admin
"""
import pytest
from django.test import override_settings

from keel_site.audit.permissions import can_view_audit, visible_products_for


@pytest.fixture
def org(db):
    from keel.accounts.models import Organization
    return Organization.objects.create(slug='audit-org', name='Audit Org')


def _user(org, **kw):
    from keel.accounts.models import KeelUser
    base = {'username': kw.pop('username', 'u'), 'email': 'u@example.com',
            'password': 'x', 'organization': org}
    base.update(kw)
    return KeelUser.objects.create_user(**base)


def _grant(user, product, role='agency_admin', is_active=True):
    from keel.accounts.models import ProductAccess
    return ProductAccess.objects.create(
        user=user, product=product, role=role, is_active=is_active,
    )


@pytest.mark.django_db
def test_can_view_audit_anonymous_false():
    from django.contrib.auth.models import AnonymousUser
    assert can_view_audit(AnonymousUser()) is False


@pytest.mark.django_db
def test_can_view_audit_superuser_true(org):
    u = _user(org, username='su', is_superuser=True, is_staff=True)
    assert can_view_audit(u) is True


@pytest.mark.django_db
def test_can_view_audit_agency_admin_true(org):
    u = _user(org, username='aa')
    _grant(u, 'beacon', 'agency_admin')
    assert can_view_audit(u) is True


@pytest.mark.django_db
def test_can_view_audit_system_admin_true(org):
    u = _user(org, username='sa')
    _grant(u, 'beacon', 'system_admin')
    assert can_view_audit(u) is True


@pytest.mark.django_db
def test_can_view_audit_analyst_false(org):
    u = _user(org, username='analyst')
    _grant(u, 'beacon', 'analyst')
    assert can_view_audit(u) is False


@pytest.mark.django_db
def test_can_view_audit_inactive_role_false(org):
    u = _user(org, username='inactive-aa')
    _grant(u, 'beacon', 'agency_admin', is_active=False)
    assert can_view_audit(u) is False


@override_settings(KEEL_FLEET_PRODUCTS=[
    {'code': 'harbor'}, {'code': 'beacon'}, {'code': 'bounty'},
])
@pytest.mark.django_db
def test_visible_products_superuser_gets_keel_plus_fleet(org):
    u = _user(org, username='su', is_superuser=True)
    assert visible_products_for(u) == ['keel', 'harbor', 'beacon', 'bounty']


@override_settings(KEEL_FLEET_PRODUCTS=[
    {'code': 'harbor'}, {'code': 'beacon'}, {'code': 'bounty'},
])
@pytest.mark.django_db
def test_visible_products_agency_admin_scoped_to_their_products(org):
    """Decision H1: agency_admin of Beacon does NOT see Keel or Harbor."""
    u = _user(org, username='aa')
    _grant(u, 'beacon', 'agency_admin')
    assert visible_products_for(u) == ['beacon']
    assert 'keel' not in visible_products_for(u)
    assert 'harbor' not in visible_products_for(u)


@override_settings(KEEL_FLEET_PRODUCTS=[
    {'code': 'harbor'}, {'code': 'beacon'},
])
@pytest.mark.django_db
def test_visible_products_intersects_with_fleet(org):
    """Decision H2: stale ProductAccess for a decommissioned product
    must not leak visibility."""
    u = _user(org, username='aa')
    _grant(u, 'beacon', 'agency_admin')
    _grant(u, 'decommissioned-product', 'agency_admin')
    assert visible_products_for(u) == ['beacon']


@override_settings(KEEL_FLEET_PRODUCTS=[{'code': 'beacon'}])
@pytest.mark.django_db
def test_visible_products_anonymous_empty():
    from django.contrib.auth.models import AnonymousUser
    assert visible_products_for(AnonymousUser()) == []
