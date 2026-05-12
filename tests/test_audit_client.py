"""Tests for keel.feed.client.fetch_product_audit status discriminator."""
from __future__ import annotations

from unittest.mock import patch

import requests

from keel.feed.client import fetch_product_audit


class _FakeResp:
    def __init__(self, status_code, body=None, raise_value=False):
        self.status_code = status_code
        self._body = body
        self._raise = raise_value
        self.text = '' if body is None else str(body)

    def json(self):
        if self._raise:
            raise ValueError('Expecting value')
        return self._body


def test_status_ok_on_200_with_json():
    fake = _FakeResp(200, body={'items': [], 'product': 'beacon'})
    with patch('keel.feed.client._session.get', return_value=fake):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='2026-05-12T00:00:00', window_end='2026-05-12T01:00:00',
        )
    assert result['status'] == 'ok'
    assert result['data'] == {'items': [], 'product': 'beacon'}
    assert result['error'] == ''


def test_status_pending_on_404():
    fake = _FakeResp(404, body='Not Found')
    with patch('keel.feed.client._session.get', return_value=fake):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
        )
    assert result['status'] == 'pending'
    assert result['data'] is None


def test_status_unauthorized_on_401():
    fake = _FakeResp(401, body='Invalid API key.')
    with patch('keel.feed.client._session.get', return_value=fake):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
        )
    assert result['status'] == 'unauthorized'


def test_status_unauthorized_on_403():
    fake = _FakeResp(403)
    with patch('keel.feed.client._session.get', return_value=fake):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
        )
    assert result['status'] == 'unauthorized'


def test_status_error_on_5xx():
    fake = _FakeResp(500, body='Internal Server Error')
    with patch('keel.feed.client._session.get', return_value=fake):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
        )
    assert result['status'] == 'error'


def test_status_error_on_malformed_json():
    fake = _FakeResp(200, body=None, raise_value=True)
    with patch('keel.feed.client._session.get', return_value=fake):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
        )
    assert result['status'] == 'error'
    assert 'Malformed JSON' in result['error']


def test_status_pending_on_connection_error():
    with patch('keel.feed.client._session.get', side_effect=requests.ConnectionError('refused')):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
        )
    assert result['status'] == 'pending'
    assert 'refused' in result['error']


def test_status_timeout_on_read_timeout():
    with patch('keel.feed.client._session.get', side_effect=requests.Timeout('read timeout')):
        result = fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
        )
    assert result['status'] == 'timeout'


def test_params_include_filter_values():
    """q, actions, limit, window_* all forwarded as query params."""
    captured = {}

    def fake_get(url, headers, params, timeout):
        captured.update(params)
        return _FakeResp(200, body={'items': []})

    with patch('keel.feed.client._session.get', side_effect=fake_get):
        fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='2026-05-12T00:00:00',
            window_end='2026-05-12T01:00:00',
            q='dan',
            actions=['login', 'security_event'],
            limit=200,
        )

    assert captured['window_start'] == '2026-05-12T00:00:00'
    assert captured['window_end'] == '2026-05-12T01:00:00'
    assert captured['q'] == 'dan'
    assert captured['actions'] == 'login,security_event'
    assert captured['limit'] == '200'


def test_empty_q_and_actions_omitted():
    captured = {}

    def fake_get(url, headers, params, timeout):
        captured.update(params)
        return _FakeResp(200, body={'items': []})

    with patch('keel.feed.client._session.get', side_effect=fake_get):
        fetch_product_audit(
            'https://beacon.test/api/v1/audit-feed/', 'k',
            window_start='a', window_end='b',
            q='', actions=(),
        )

    assert 'q' not in captured
    assert 'actions' not in captured
