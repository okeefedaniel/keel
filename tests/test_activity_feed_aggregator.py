"""Tests for the cross-product activity-feed aggregator (keel v0.47.1).

``activity_feed_view`` is the per-product decorator that mirrors
``audit_feed_view``. ``fetch_product_activity`` is the client used by Keel's
``/ops/`` Row 2 to fan out across the suite. Both are exercised in unit
tests here; full HTTP-level integration is covered by the broader keel
test suite.
"""
from unittest.mock import patch

import pytest


def test_activity_feed_view_is_exported_at_package_root():
    """The decorator and client must be importable from `keel.feed` so the
    per-product example file's `from keel.feed import activity_feed_view`
    line works without diving into private modules."""
    from keel.feed import activity_feed_view, fetch_product_activity
    assert callable(activity_feed_view)
    assert callable(fetch_product_activity)


def test_activity_feed_view_returns_503_when_api_key_unset(settings):
    """Same auth contract as audit_feed_view — no HELM_FEED_API_KEY means
    no aggregation surface is reachable."""
    from django.test import RequestFactory
    from keel.feed import activity_feed_view

    settings.HELM_FEED_API_KEY = ''
    settings.HELM_FEED_API_KEY_PRIMARY = ''  # belt-and-suspenders
    settings.HELM_FEED_API_KEY_SECONDARY = ''
    settings.DEMO_MODE = False

    @activity_feed_view
    def _build(request):
        return {'items': []}

    request = RequestFactory().get('/api/v1/activity-feed/')
    response = _build(request)
    assert response.status_code == 503


def test_activity_feed_view_rejects_missing_bearer_auth(settings):
    """A configured aggregator with NO Authorization header → 401."""
    from django.test import RequestFactory
    from keel.feed import activity_feed_view

    settings.HELM_FEED_API_KEY = 'test-key-do-not-use-in-prod'
    settings.DEMO_MODE = False

    @activity_feed_view
    def _build(request):
        return {'items': []}

    request = RequestFactory().get('/api/v1/activity-feed/')
    response = _build(request)
    assert response.status_code == 401


def test_activity_feed_view_accepts_valid_bearer_and_returns_payload(settings):
    """Valid Authorization → 200, payload includes the normalized fetched_at
    + product fields."""
    from django.test import RequestFactory
    from keel.feed import activity_feed_view

    settings.HELM_FEED_API_KEY = 'test-key-do-not-use-in-prod'
    settings.DEMO_MODE = False
    settings.KEEL_PRODUCT_CODE = 'testproduct'

    @activity_feed_view
    def _build(request):
        return {
            'items': [{'id': '1', 'verb': 'test.event', 'summary': 'hi'}],
            'total_in_window': 1,
            'capped': False,
            'window': ['2026-05-19T00:00:00', '2026-05-19T01:00:00'],
        }

    factory = RequestFactory()
    request = factory.get(
        '/api/v1/activity-feed/?window_start=2026-05-19T00:00:00',
        HTTP_AUTHORIZATION='Bearer test-key-do-not-use-in-prod',
    )
    response = _build(request)
    assert response.status_code == 200
    import json
    body = json.loads(response.content)
    assert body['items'][0]['verb'] == 'test.event'
    # The decorator must auto-populate these if the build_fn didn't.
    assert 'fetched_at' in body
    assert body['product'] == 'testproduct'


def test_fetch_product_activity_returns_ok_envelope_on_200():
    """Client-side: a successful HTTP fetch returns status='ok' + the JSON."""
    from keel.feed import fetch_product_activity

    fake_response = type('R', (), {
        'status_code': 200,
        'json': lambda self: {'items': [{'id': 'abc'}]},
        'text': '',
    })()

    with patch('keel.feed.client._session') as mock_session:
        mock_session.get.return_value = fake_response
        result = fetch_product_activity(
            'https://product.example.com/api/v1/activity-feed/',
            api_key='abc',
            window_start='2026-05-19T00:00:00',
            window_end='2026-05-19T01:00:00',
        )

    assert result['status'] == 'ok'
    assert result['data']['items'] == [{'id': 'abc'}]
    assert result['error'] == ''


def test_fetch_product_activity_returns_pending_on_404():
    """A 404 (endpoint not mounted yet) renders as a 'pending' gray chip on
    /ops/ — products mid-rollout don't break the aggregator."""
    from keel.feed import fetch_product_activity

    fake_response = type('R', (), {
        'status_code': 404,
        'json': lambda self: {},
        'text': 'not found',
    })()

    with patch('keel.feed.client._session') as mock_session:
        mock_session.get.return_value = fake_response
        result = fetch_product_activity(
            'https://product.example.com/api/v1/activity-feed/',
            api_key='abc',
            window_start='2026-05-19T00:00:00',
            window_end='2026-05-19T01:00:00',
        )

    assert result['status'] == 'pending'
    assert result['data'] is None


def test_fetch_product_activity_passes_verb_filter_and_status_through():
    """Verb + status filters must reach the wire so the per-product SQL
    can apply them before its row cap."""
    from keel.feed import fetch_product_activity

    fake_response = type('R', (), {
        'status_code': 200,
        'json': lambda self: {'items': []},
        'text': '',
    })()

    with patch('keel.feed.client._session') as mock_session:
        mock_session.get.return_value = fake_response
        fetch_product_activity(
            'https://product.example.com/api/v1/activity-feed/',
            api_key='abc',
            window_start='2026-05-19T00:00:00',
            window_end='2026-05-19T01:00:00',
            verbs=['grants_gov.polled', 'salesforce.synced'],
            status='failed',
        )

    call_kwargs = mock_session.get.call_args.kwargs
    assert call_kwargs['params']['verbs'] == 'grants_gov.polled,salesforce.synced'
    assert call_kwargs['params']['status'] == 'failed'
