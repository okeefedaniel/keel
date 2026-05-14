"""Tests for keel.mentions.beacon — best-effort cross-product client.

Pins the contract that every failure path returns gracefully without
raising:

- is_available() reads BEACON_INTAKE_URL + BEACON_INTAKE_API_KEY
- search_contacts(q) returns [] when Beacon not configured, network
  fails, returns non-2xx, or returns malformed JSON
- append_contact_mention(...) returns (True, '') on 2xx, (False, '...')
  on every other outcome — NEVER raises
"""
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from keel.mentions import beacon as beacon_client


@override_settings(BEACON_INTAKE_URL='', BEACON_INTAKE_API_KEY='')
def test_is_available_false_when_unconfigured():
    assert beacon_client.is_available() is False


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_is_available_true_when_both_set():
    assert beacon_client.is_available() is True


@override_settings(BEACON_INTAKE_URL='', BEACON_INTAKE_API_KEY='')
def test_search_contacts_empty_when_unconfigured():
    assert beacon_client.search_contacts('sarah') == []


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_search_contacts_empty_when_query_too_short():
    assert beacon_client.search_contacts('s') == []
    assert beacon_client.search_contacts('') == []


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_search_contacts_returns_results_on_2xx():
    fake = MagicMock()
    fake.raise_for_status.return_value = None
    fake.json.return_value = [
        {'slug': 'sarah-jones', 'display_name': 'Sarah Jones',
         'organization': 'Acme', 'url': 'https://beacon.example/c/sarah'},
    ]
    with patch.object(beacon_client, '_http') as http:
        http.return_value.get.return_value = fake
        out = beacon_client.search_contacts('sarah')
    assert out[0]['slug'] == 'sarah-jones'


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_search_contacts_silent_on_network_error():
    with patch.object(beacon_client, '_http') as http:
        http.return_value.get.side_effect = ConnectionError('boom')
        assert beacon_client.search_contacts('sarah') == []


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_search_contacts_silent_on_5xx():
    fake = MagicMock()
    fake.raise_for_status.side_effect = Exception('500 Server Error')
    with patch.object(beacon_client, '_http') as http:
        http.return_value.get.return_value = fake
        assert beacon_client.search_contacts('sarah') == []


@override_settings(BEACON_INTAKE_URL='', BEACON_INTAKE_API_KEY='')
def test_append_returns_false_when_unconfigured():
    ok, err = beacon_client.append_contact_mention(
        'sarah', source_product='harbor', source_url='u',
        source_label='l', author_username='a', excerpt='e',
    )
    assert ok is False
    assert 'configured' in err


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_append_returns_true_on_2xx():
    fake = MagicMock()
    fake.status_code = 201
    with patch.object(beacon_client, '_http') as http:
        http.return_value.post.return_value = fake
        ok, err = beacon_client.append_contact_mention(
            'sarah', source_product='harbor',
            source_url='https://harbor/applications/1/',
            source_label='Bridgeport Grant',
            author_username='dok', excerpt='please review',
        )
    assert ok is True
    assert err == ''


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_append_returns_gone_on_410():
    fake = MagicMock()
    fake.status_code = 410
    fake.text = 'contact deleted'
    with patch.object(beacon_client, '_http') as http:
        http.return_value.post.return_value = fake
        ok, err = beacon_client.append_contact_mention(
            'sarah', source_product='harbor', source_url='u',
            source_label='l', author_username='a', excerpt='e',
        )
    assert ok is False
    assert err == 'gone'


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_append_never_raises_on_network_error():
    with patch.object(beacon_client, '_http') as http:
        http.return_value.post.side_effect = ConnectionError('boom')
        ok, err = beacon_client.append_contact_mention(
            'sarah', source_product='harbor', source_url='u',
            source_label='l', author_username='a', excerpt='e',
        )
    assert ok is False
    assert 'boom' in err
