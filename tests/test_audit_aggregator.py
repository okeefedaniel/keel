"""Tests for keel_site.audit.aggregator.aggregate_audit.

Exercises the fan-out / merge / status-discriminator paths with
``fetch_product_audit`` mocked so no real HTTP is required.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from django.test import override_settings

from keel_site.audit.aggregator import (
    AggregateResult,
    ProductStatus,
    _audit_feed_url_for,
    aggregate_audit,
)


def _window():
    end = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    start = datetime(2026, 5, 12, 11, 0, tzinfo=timezone.utc)
    return start, end


def test_audit_feed_url_strips_path():
    assert _audit_feed_url_for('https://harbor.docklabs.ai/dashboard/') == \
        'https://harbor.docklabs.ai/api/v1/audit-feed/'
    assert _audit_feed_url_for('https://x.test/some/deep/path/?q=1#frag') == \
        'https://x.test/api/v1/audit-feed/'


@override_settings(
    KEEL_FLEET_PRODUCTS=[
        {'code': 'harbor', 'url': 'https://harbor.test/dashboard/'},
        {'code': 'beacon', 'url': 'https://beacon.test/dashboard/'},
    ],
    HELM_FEED_API_KEY='k',
)
def test_aggregate_audit_merges_in_time_desc_order():
    start, end = _window()
    fake = {
        'https://harbor.test/api/v1/audit-feed/': {
            'status': 'ok', 'duration_ms': 50, 'error': '',
            'data': {'items': [
                {'timestamp': '2026-05-12T11:30:00', 'action': 'login',
                 'entity_type': 'session', 'entity_id': '1'},
                {'timestamp': '2026-05-12T11:10:00', 'action': 'update',
                 'entity_type': 'grant', 'entity_id': '4821'},
            ], 'total_in_window': 2, 'capped': False},
        },
        'https://beacon.test/api/v1/audit-feed/': {
            'status': 'ok', 'duration_ms': 70, 'error': '',
            'data': {'items': [
                {'timestamp': '2026-05-12T11:45:00', 'action': 'create',
                 'entity_type': 'contact', 'entity_id': '99'},
            ], 'total_in_window': 1, 'capped': False},
        },
    }

    def fake_fetch(url, key, **kw):
        return fake[url]

    with patch('keel_site.audit.aggregator.fetch_product_audit',
               side_effect=fake_fetch):
        result = aggregate_audit(
            visible_products=['harbor', 'beacon'],
            window_start=start, window_end=end,
        )

    assert [r['entity_id'] for r in result.rows] == ['99', '1', '4821']
    assert result.per_product['harbor'].status == 'ok'
    assert result.per_product['beacon'].status == 'ok'
    assert result.per_product['harbor'].capped is False


@override_settings(
    KEEL_FLEET_PRODUCTS=[
        {'code': 'harbor', 'url': 'https://harbor.test/dashboard/'},
        {'code': 'beacon', 'url': 'https://beacon.test/dashboard/'},
    ],
    HELM_FEED_API_KEY='k',
)
def test_aggregate_audit_surfaces_per_product_status_mix():
    start, end = _window()
    fake = {
        'https://harbor.test/api/v1/audit-feed/': {
            'status': 'timeout', 'duration_ms': 5000, 'error': 'Timeout', 'data': None,
        },
        'https://beacon.test/api/v1/audit-feed/': {
            'status': 'ok', 'duration_ms': 30, 'error': '',
            'data': {'items': [], 'total_in_window': 0, 'capped': False},
        },
    }

    def fake_fetch(url, key, **kw):
        return fake[url]

    with patch('keel_site.audit.aggregator.fetch_product_audit',
               side_effect=fake_fetch):
        result = aggregate_audit(
            visible_products=['harbor', 'beacon'],
            window_start=start, window_end=end,
        )

    assert result.per_product['harbor'].status == 'timeout'
    assert result.per_product['beacon'].status == 'ok'
    assert result.rows == []


@override_settings(KEEL_FLEET_PRODUCTS=[], HELM_FEED_API_KEY='k')
def test_aggregate_audit_empty_visible_products_returns_empty():
    start, end = _window()
    result = aggregate_audit(
        visible_products=[], window_start=start, window_end=end,
    )
    assert isinstance(result, AggregateResult)
    assert result.rows == []
    assert result.per_product == {}


@override_settings(
    KEEL_FLEET_PRODUCTS=[{'code': 'harbor', 'url': 'https://harbor.test/dashboard/'}],
    HELM_FEED_API_KEY='k',
)
def test_aggregate_audit_capped_flag_propagates():
    start, end = _window()
    fake_resp = {
        'status': 'ok', 'duration_ms': 100, 'error': '',
        'data': {'items': [{'timestamp': '2026-05-12T11:50:00'}],
                 'total_in_window': 5000, 'capped': True},
    }
    with patch('keel_site.audit.aggregator.fetch_product_audit',
               return_value=fake_resp):
        result = aggregate_audit(
            visible_products=['harbor'],
            window_start=start, window_end=end,
        )
    assert result.per_product['harbor'].capped is True
    assert result.per_product['harbor'].total_in_window == 5000


@pytest.mark.django_db
def test_aggregate_audit_keel_local_runs_in_thread_pool():
    """When 'keel' is in visible_products, fetch_keel_local supplies rows."""
    start, end = _window()
    with override_settings(KEEL_FLEET_PRODUCTS=[]):
        result = aggregate_audit(
            visible_products=['keel'],
            window_start=start, window_end=end,
        )
    # keel-local returns 'ok' even with zero rows in the DB
    assert result.per_product['keel'].status == 'ok'
    assert result.rows == [] or all(r.get('product') == 'keel' for r in result.rows)


def test_aggregate_audit_security_event_count():
    start, end = _window()
    fake_resp = {
        'status': 'ok', 'duration_ms': 10, 'error': '',
        'data': {'items': [
            {'timestamp': '2026-05-12T11:55', 'action': 'security_event'},
            {'timestamp': '2026-05-12T11:50', 'action': 'login'},
            {'timestamp': '2026-05-12T11:45', 'action': 'security_event'},
        ], 'total_in_window': 3, 'capped': False},
    }
    with override_settings(
        KEEL_FLEET_PRODUCTS=[{'code': 'harbor', 'url': 'https://x.test/dashboard/'}],
        HELM_FEED_API_KEY='k',
    ), patch('keel_site.audit.aggregator.fetch_product_audit', return_value=fake_resp):
        result = aggregate_audit(
            visible_products=['harbor'],
            window_start=start, window_end=end,
        )
    assert result.security_event_count == 2
