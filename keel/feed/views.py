"""Shared views and decorators for exposing helm-feed endpoints.

Each product implements a ``build_feed()`` function that returns a dict
conforming to the ProductFeed contract. The ``helm_feed_view`` decorator
handles auth, error handling, and the demo-mode fallback.
"""
import functools
import hmac
import json
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

_RATE_LIMIT_REQUESTS = 60
_RATE_LIMIT_WINDOW_SECONDS = 60


def _rate_limited(api_key: str) -> bool:
    """Per-key token bucket: 60 req / 60 s."""
    key = f'keel:helm_feed_rate:{api_key[:16]}'
    now = time.time()
    bucket = cache.get(key) or []
    bucket = [t for t in bucket if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= _RATE_LIMIT_REQUESTS:
        return True
    bucket.append(now)
    cache.set(key, bucket, timeout=_RATE_LIMIT_WINDOW_SECONDS)
    return False


def helm_feed_view(build_feed_func):
    """Decorator that turns a ``build_feed(request) -> dict`` into a
    secured /api/v1/helm-feed/ endpoint.

    Auth: Bearer token via ``HELM_FEED_API_KEY`` setting/env var.
    In DEMO_MODE, auth is bypassed so the demo Helm instance can pull
    feeds without configuring secrets.

    The wrapped function should return a dict matching the ProductFeed
    contract (product, product_label, product_url, metrics, action_items,
    alerts, sparklines).
    """

    @csrf_exempt
    @require_GET
    @functools.wraps(build_feed_func)
    def wrapper(request):
        demo_mode = getattr(settings, 'DEMO_MODE', False)

        # Resolve the expected key — demo hosts accept HELM_FEED_DEMO_API_KEY
        # if configured, falling back to HELM_FEED_API_KEY.
        if demo_mode:
            expected = (
                getattr(settings, 'HELM_FEED_DEMO_API_KEY', '')
                or getattr(settings, 'HELM_FEED_API_KEY', '')
                or ''
            )
        else:
            expected = getattr(settings, 'HELM_FEED_API_KEY', '') or ''

        if not expected:
            return JsonResponse(
                {'error': 'Helm feed not configured (HELM_FEED_API_KEY missing).'},
                status=503,
            )

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer ') or not hmac.compare_digest(
            auth_header[7:].strip(), expected,
        ):
            return JsonResponse({'error': 'Invalid API key.'}, status=401)

        if _rate_limited(expected):
            return JsonResponse(
                {'error': 'Rate limit exceeded.'},
                status=429,
            )

        # 60s cache keyed by path — helm scrapes these often; the
        # aggregation is expensive.
        cache_key = f'keel:helm_feed_cache:{request.path}'
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse(cached)

        try:
            feed_data = build_feed_func(request)
        except Exception:
            logger.exception('Error building helm feed for %s', request.path)
            return JsonResponse(
                {'error': 'Internal error building feed.'},
                status=500,
            )

        # Inject timestamp if not set
        if 'updated_at' not in feed_data or not feed_data['updated_at']:
            feed_data['updated_at'] = timezone.now().isoformat()

        cache.set(cache_key, feed_data, timeout=60)
        return JsonResponse(feed_data)

    return wrapper
