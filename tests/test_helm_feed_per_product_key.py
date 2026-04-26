"""Per-product helm-feed keys + suite-wide fallback."""
from __future__ import annotations

from django.test import RequestFactory, override_settings

from keel.feed import views as feed_views


def _bearer(key: str):
    rf = RequestFactory()
    return rf.get('/api/v1/helm-feed/', HTTP_AUTHORIZATION=f'Bearer {key}')


@override_settings(
    HELM_FEED_API_KEYS={'harbor': 'harbor-key', 'beacon': 'beacon-key'},
    HELM_FEED_API_KEY='',
    DEMO_MODE=False,
)
def test_per_product_key_accepted():
    matched = feed_views._authenticate_helm_bearer(_bearer('harbor-key'))
    assert matched == 'harbor-key'


@override_settings(
    HELM_FEED_API_KEYS={'harbor': 'harbor-key'},
    HELM_FEED_API_KEY='',
    DEMO_MODE=False,
)
def test_wrong_key_rejected():
    assert feed_views._authenticate_helm_bearer(_bearer('attacker-key')) is None


@override_settings(
    HELM_FEED_API_KEYS={},
    HELM_FEED_API_KEY='suite-key',
    DEMO_MODE=False,
)
def test_suite_wide_key_still_works():
    assert feed_views._authenticate_helm_bearer(_bearer('suite-key')) == 'suite-key'


@override_settings(
    HELM_FEED_API_KEYS={},
    HELM_FEED_API_KEY='',
    DEMO_MODE=False,
)
def test_no_keys_configured_returns_none():
    assert feed_views._authenticate_helm_bearer(_bearer('anything')) is None
