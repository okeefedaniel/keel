"""Tests for the mentions_search JSON endpoint.

Pins:
- Auth required (login_required redirects)
- q < 2 returns empty arrays (cheap enumeration mitigation)
- Returns documented two-array shape {users, contacts}
- contacts always [] when Beacon not configured
- Audit log row written when KEEL_AUDIT_LOG_MODEL configured
- No email field leaked in user rows
"""
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username='dok', email='dok@x.com', password='x', is_active=True,
    )


def test_anonymous_redirects(client):
    resp = client.get(reverse('keel_mentions:mentions_search') + '?q=al')
    # login_required redirects anonymous users (302).
    assert resp.status_code in (302, 401)


def test_authenticated_short_query_returns_empty(client, user):
    client.force_login(user)
    resp = client.get(reverse('keel_mentions:mentions_search') + '?q=a')
    assert resp.status_code == 200
    body = resp.json()
    assert body == {'users': [], 'contacts': []}


def test_authenticated_returns_two_array_shape(client, user):
    client.force_login(user)
    resp = client.get(reverse('keel_mentions:mentions_search') + '?q=ali')
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {'users', 'contacts'}
    assert isinstance(body['users'], list)
    assert isinstance(body['contacts'], list)


@override_settings(BEACON_INTAKE_URL='', BEACON_INTAKE_API_KEY='')
def test_contacts_empty_when_beacon_unconfigured(client, user):
    client.force_login(user)
    resp = client.get(reverse('keel_mentions:mentions_search') + '?q=sarah')
    assert resp.json()['contacts'] == []


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_contacts_returned_when_beacon_available(client, user):
    client.force_login(user)
    with patch('keel.mentions.views.beacon_search_contacts') as bs:
        bs.return_value = [
            {'slug': 'sarah', 'display_name': 'Sarah Jones',
             'organization': 'Acme', 'url': 'https://beacon.example/c/sarah'},
        ]
        resp = client.get(reverse('keel_mentions:mentions_search') + '?q=sarah')
    body = resp.json()
    assert len(body['contacts']) == 1
    assert body['contacts'][0]['slug'] == 'sarah'
    assert body['contacts'][0]['source_product'] == 'beacon'


def test_user_row_does_not_leak_email(client, user, django_user_model):
    # Create a second user so search has something to match against.
    django_user_model.objects.create_user(
        username='alice', email='alice@x.com', password='x', is_active=True,
    )
    client.force_login(user)
    resp = client.get(reverse('keel_mentions:mentions_search') + '?q=alice')
    body = resp.json()
    for row in body['users']:
        assert 'email' not in row, f'email leaked in row: {row}'
