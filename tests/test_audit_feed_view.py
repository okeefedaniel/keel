"""Tests for keel.feed.audit_feed_view decorator.

Mirrors test_helm_feed_per_product_key.py + test_helm_inbox_view.py patterns.
"""
from __future__ import annotations

import json

from django.core.cache import cache
from django.test import RequestFactory, override_settings

from keel.feed.views import audit_feed_view


def _bearer(path: str, key: str, **params):
    rf = RequestFactory()
    return rf.get(path, params, HTTP_AUTHORIZATION=f'Bearer {key}')


def _build(request):
    return {
        'items': [{'id': '1', 'description': 'x'}],
        'total_in_window': 1,
        'capped': False,
        'window': ['2026-05-12T00:00:00', '2026-05-12T01:00:00'],
        'product': 'beacon',
    }


@override_settings(
    HELM_FEED_API_KEY='audit-key',
    HELM_FEED_API_KEYS={},
    DEMO_MODE=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-test'}},
)
def test_valid_bearer_returns_payload():
    cache.clear()
    view = audit_feed_view(_build)
    resp = view(_bearer('/api/v1/audit-feed/', 'audit-key', window_start='2026-05-12T00:00:00', window_end='2026-05-12T01:00:00'))
    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert body['items'] == [{'id': '1', 'description': 'x'}]
    assert body['product'] == 'beacon'
    assert 'fetched_at' in body


@override_settings(
    HELM_FEED_API_KEY='audit-key',
    HELM_FEED_API_KEYS={},
    DEMO_MODE=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-bad-key'}},
)
def test_invalid_bearer_returns_401():
    cache.clear()
    view = audit_feed_view(_build)
    resp = view(_bearer('/api/v1/audit-feed/', 'wrong-key'))
    assert resp.status_code == 401


@override_settings(
    HELM_FEED_API_KEY='',
    HELM_FEED_API_KEYS={},
    DEMO_MODE=False,
)
def test_unconfigured_returns_503():
    view = audit_feed_view(_build)
    resp = view(_bearer('/api/v1/audit-feed/', 'anything'))
    assert resp.status_code == 503


@override_settings(
    HELM_FEED_API_KEY='audit-key',
    HELM_FEED_API_KEYS={},
    DEMO_MODE=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-cache-isolation'}},
)
def test_cache_key_isolates_different_query_params():
    """Two requests with different `q` query params must not share a cache slot."""
    cache.clear()
    calls = {'n': 0}

    def build(request):
        calls['n'] += 1
        return {'items': [{'q': request.GET.get('q', '')}], 'capped': False}

    view = audit_feed_view(build)
    r1 = view(_bearer('/api/v1/audit-feed/', 'audit-key', q='alpha'))
    r2 = view(_bearer('/api/v1/audit-feed/', 'audit-key', q='beta'))
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls['n'] == 2  # each q got its own build call
    assert json.loads(r1.content)['items'][0]['q'] == 'alpha'
    assert json.loads(r2.content)['items'][0]['q'] == 'beta'


@override_settings(
    HELM_FEED_API_KEY='audit-key',
    HELM_FEED_API_KEYS={},
    DEMO_MODE=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-cache-hit'}},
)
def test_cache_hit_avoids_rebuild():
    cache.clear()
    calls = {'n': 0}

    def build(request):
        calls['n'] += 1
        return {'items': [], 'capped': False}

    view = audit_feed_view(build)
    view(_bearer('/api/v1/audit-feed/', 'audit-key', q='same'))
    view(_bearer('/api/v1/audit-feed/', 'audit-key', q='same'))
    assert calls['n'] == 1  # second call served from cache


@override_settings(
    HELM_FEED_API_KEY='audit-key',
    HELM_FEED_API_KEYS={},
    DEMO_MODE=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'audit-builder-err'}},
)
def test_builder_exception_returns_500():
    cache.clear()

    def build(request):
        raise RuntimeError('boom')

    view = audit_feed_view(build)
    resp = view(_bearer('/api/v1/audit-feed/', 'audit-key'))
    assert resp.status_code == 500
