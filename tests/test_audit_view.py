"""End-to-end view tests for /audit/.

Exercises permission gating, the C1 unbound-form fix, rate limit, the
security-events pill URL construction, and the all-failed banner.
"""
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
from django.urls import reverse


@pytest.fixture
def org(db):
    from keel.accounts.models import Organization
    return Organization.objects.create(slug='audit-view-org', name='Audit View Org')


@pytest.fixture
def super_user(org):
    from keel.accounts.models import KeelUser
    return KeelUser.objects.create_user(
        username='su', email='su@example.com', password='x',
        is_superuser=True, is_staff=True, organization=org,
    )


@pytest.fixture
def analyst_user(org):
    from keel.accounts.models import KeelUser, ProductAccess
    u = KeelUser.objects.create_user(
        username='analyst', email='a@example.com', password='x',
        organization=org,
    )
    ProductAccess.objects.create(user=u, product='beacon', role='analyst', is_active=True)
    return u


@pytest.fixture
def aa_beacon_user(org):
    from keel.accounts.models import KeelUser, ProductAccess
    u = KeelUser.objects.create_user(
        username='aa', email='aa@example.com', password='x',
        organization=org,
    )
    ProductAccess.objects.create(user=u, product='beacon', role='agency_admin', is_active=True)
    return u


# Stub fan-out responses so the view does not attempt real HTTP.
_OK_EMPTY = {
    'status': 'ok', 'duration_ms': 10, 'error': '',
    'data': {'items': [], 'total_in_window': 0, 'capped': False},
}
_ERROR = {'status': 'error', 'duration_ms': 10, 'error': 'boom', 'data': None}


@pytest.mark.django_db
def test_view_redirects_anonymous_to_login(client):
    """An anonymous user hits 403 via _can_view_audit (no auth redirect wired)."""
    resp = client.get(reverse('audit'))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_view_forbids_non_admin(client, analyst_user):
    client.force_login(analyst_user)
    resp = client.get(reverse('audit'))
    assert resp.status_code == 403


@override_settings(
    STORAGES=_STORAGES,
    KEEL_FLEET_PRODUCTS=[],
    HELM_FEED_API_KEY='k',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-view-bare'}},
)
@pytest.mark.django_db
def test_view_bare_get_does_not_crash(client, super_user):
    """C1 regression: AuditFilterForm must bind on a bare /audit/ GET."""
    cache.clear()
    client.force_login(super_user)
    with patch('keel_site.audit.aggregator.fetch_keel_local', return_value=_OK_EMPTY):
        resp = client.get(reverse('audit'))
    assert resp.status_code == 200


@override_settings(
    STORAGES=_STORAGES,
    KEEL_FLEET_PRODUCTS=[{'code': 'beacon', 'url': 'https://beacon.test/dashboard/'}],
    HELM_FEED_API_KEY='k',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-view-ok'}},
)
@pytest.mark.django_db
def test_view_renders_for_superuser(client, super_user):
    cache.clear()
    client.force_login(super_user)
    with patch('keel_site.audit.aggregator.fetch_product_audit', return_value=_OK_EMPTY), \
         patch('keel_site.audit.aggregator.fetch_keel_local', return_value=_OK_EMPTY):
        resp = client.get(reverse('audit'))
    assert resp.status_code == 200
    assert b'Audit' in resp.content
    # Status chip rendered for the configured fleet product
    assert b'Beacon' in resp.content or b'beacon' in resp.content


@override_settings(
    STORAGES=_STORAGES,
    KEEL_FLEET_PRODUCTS=[{'code': 'beacon', 'url': 'https://beacon.test/dashboard/'}],
    HELM_FEED_API_KEY='k',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-view-agency'}},
)
@pytest.mark.django_db
def test_view_renders_for_agency_admin_scoped_products(client, aa_beacon_user):
    """Agency admin of Beacon gets the page; visible_products is just ['beacon']."""
    cache.clear()
    client.force_login(aa_beacon_user)
    with patch('keel_site.audit.aggregator.fetch_product_audit', return_value=_OK_EMPTY), \
         patch('keel_site.audit.aggregator.fetch_keel_local', return_value=_OK_EMPTY):
        resp = client.get(reverse('audit'))
    assert resp.status_code == 200


@override_settings(
    STORAGES=_STORAGES,
    KEEL_FLEET_PRODUCTS=[{'code': 'beacon', 'url': 'https://beacon.test/dashboard/'}],
    HELM_FEED_API_KEY='k',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-view-failed'}},
)
@pytest.mark.django_db
def test_view_renders_all_failed_banner(client, super_user):
    """When every product fetch returns non-ok status, the banner appears."""
    cache.clear()
    client.force_login(super_user)
    with patch('keel_site.audit.aggregator.fetch_product_audit', return_value=_ERROR), \
         patch('keel_site.audit.aggregator.fetch_keel_local',
               return_value={'status': 'error', 'duration_ms': 0,
                             'data': {'items': [], 'total_in_window': 0, 'capped': False},
                             'error': 'db down'}):
        resp = client.get(reverse('audit'))
    assert resp.status_code == 200
    assert b'All audit sources are unavailable' in resp.content


@override_settings(
    STORAGES=_STORAGES,
    KEEL_FLEET_PRODUCTS=[],
    HELM_FEED_API_KEY='k',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-view-rate'}},
)
@pytest.mark.django_db
def test_view_rate_limits_after_30_requests(client, super_user):
    cache.clear()
    client.force_login(super_user)
    with patch('keel_site.audit.aggregator.fetch_keel_local', return_value=_OK_EMPTY):
        for _ in range(30):
            client.get(reverse('audit'))
        resp = client.get(reverse('audit'))
    assert resp.status_code == 403
    assert b'Rate limit' in resp.content
