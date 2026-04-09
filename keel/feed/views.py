"""Shared views and decorators for exposing helm-feed endpoints.

Each product implements a ``build_feed()`` function that returns a dict
conforming to the ProductFeed contract. The ``helm_feed_view`` decorator
handles auth, error handling, and the demo-mode fallback.
"""
import functools
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


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

        # Auth check — skip in demo mode
        if not demo_mode:
            api_key = getattr(settings, 'HELM_FEED_API_KEY', '') or ''
            if not api_key:
                return JsonResponse(
                    {'error': 'Helm feed not configured (HELM_FEED_API_KEY missing).'},
                    status=503,
                )

            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if not auth_header.startswith('Bearer ') or not hmac.compare_digest(
                auth_header[7:].strip(), api_key
            ):
                return JsonResponse({'error': 'Invalid API key.'}, status=401)

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

        return JsonResponse(feed_data)

    return wrapper
