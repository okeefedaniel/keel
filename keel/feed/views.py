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


def _accepted_keys(*, demo_mode: bool) -> list[str]:
    """Return the list of bearer tokens that are accepted on this service.

    Per-product keys (``HELM_FEED_API_KEYS`` dict) are preferred; the
    suite-wide ``HELM_FEED_API_KEY`` is honored as a fallback so existing
    deploys keep working. In ``DEMO_MODE`` the demo-specific key is also
    accepted.
    """
    keys: list[str] = []
    per_product = getattr(settings, 'HELM_FEED_API_KEYS', None) or {}
    if isinstance(per_product, dict):
        keys.extend(v for v in per_product.values() if v)
    suite = getattr(settings, 'HELM_FEED_API_KEY', '') or ''
    if suite:
        keys.append(suite)
    if demo_mode:
        demo = getattr(settings, 'HELM_FEED_DEMO_API_KEY', '') or ''
        if demo:
            keys.append(demo)
    # Dedupe while preserving order.
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _authenticate_helm_bearer(request) -> str | None:
    """Return the matched key on success, ``None`` on failure.

    Compares against every accepted key with constant-time semantics so a
    Helm aggregator carrying any one of N per-product keys is accepted.
    """
    demo_mode = getattr(settings, 'DEMO_MODE', False)
    accepted = _accepted_keys(demo_mode=demo_mode)
    if not accepted:
        return None
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return None
    presented = auth_header[7:].strip()
    matched = None
    # Compare against every key — never short-circuit, so timing doesn't
    # leak which key matched.
    for k in accepted:
        if hmac.compare_digest(presented, k):
            matched = k
    return matched


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
        if not _accepted_keys(demo_mode=getattr(settings, 'DEMO_MODE', False)):
            return JsonResponse(
                {'error': 'Helm feed not configured (HELM_FEED_API_KEY missing).'},
                status=503,
            )

        matched = _authenticate_helm_bearer(request)
        if matched is None:
            return JsonResponse({'error': 'Invalid API key.'}, status=401)

        if _rate_limited(matched):
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


# ---------------------------------------------------------------------------
# Per-user inbox endpoint — companion to helm_feed_view
#
# The aggregate /api/v1/helm-feed/ endpoint returns "what's happening in this
# product" without any user filter. The per-user /api/v1/helm-feed/inbox/
# endpoint returns "items where THIS user is the gating dependency right now"
# (signing requests awaiting them, FOIA requests assigned to them, etc.) plus
# their unread notifications. Helm's dashboard aggregates these into the
# personal inbox column on the Today tab.
# ---------------------------------------------------------------------------

INBOX_CACHE_TTL_SECONDS = 60


def resolve_user_from_sub(sub: str):
    """OIDC ``sub`` → local KeelUser via SocialAccount (provider='keel').

    Returns None when the sub doesn't map to any local user (and the caller
    should respond with an empty inbox, not a 404, so the aggregator
    renders cleanly).
    """
    if not sub:
        return None
    from allauth.socialaccount.models import SocialAccount
    sa = (
        SocialAccount.objects
        .filter(provider='keel', uid=sub)
        .select_related('user')
        .first()
    )
    return sa.user if sa else None


def helm_inbox_view(build_inbox_func):
    """Decorator that turns a ``build_inbox(request, user) -> dict`` into a
    secured per-user inbox endpoint.

    Wrapped function signature: ``build_inbox(request, user) -> dict`` where
    ``user`` is the resolved local KeelUser. Should return a dict matching
    the ``UserInbox`` shape (product, product_label, product_url, items[],
    unread_notifications[], fetched_at, user_sub).

    Auth + rate-limit mirror :func:`helm_feed_view`. Cache key is **per-user
    per-path** so users never see each other's inbox. Unknown ``user_sub``
    returns 200 with empty items[] (not 404) so the aggregator can render
    a clean "no items" badge.
    """
    @csrf_exempt
    @require_GET
    @functools.wraps(build_inbox_func)
    def wrapper(request):
        if not _accepted_keys(demo_mode=getattr(settings, 'DEMO_MODE', False)):
            return JsonResponse(
                {'error': 'Helm feed not configured (HELM_FEED_API_KEY missing).'},
                status=503,
            )

        matched = _authenticate_helm_bearer(request)
        if matched is None:
            return JsonResponse({'error': 'Invalid API key.'}, status=401)

        if _rate_limited(matched):
            return JsonResponse({'error': 'Rate limit exceeded.'}, status=429)

        user_sub = (request.GET.get('user_sub') or '').strip()
        if not user_sub:
            return JsonResponse(
                {'error': 'user_sub query parameter is required.'},
                status=400,
            )

        # Per-user-per-path cache. NEVER cache by path alone; that would
        # serve user A's payload to user B.
        cache_key = f'keel:helm_inbox_cache:{request.path}:{user_sub}'
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse(cached)

        user = resolve_user_from_sub(user_sub)
        if user is None:
            # Derive product_url from the inbound request so the helm
            # aggregator's per-product card links to *this* product even
            # when the sub doesn't resolve. Falls back to PRODUCT_URL /
            # KEEL_PRODUCT_URL settings if the request can't supply a host
            # (cache hits, tests). Empty string was the historical value
            # and broke the helm dashboard's "Awaiting Me" links.
            product_url = (
                getattr(settings, 'KEEL_PRODUCT_URL', '')
                or getattr(settings, 'PRODUCT_URL', '')
                or request.build_absolute_uri('/').rstrip('/')
            )
            payload = {
                'product': getattr(settings, 'KEEL_PRODUCT_CODE', ''),
                'product_label': getattr(settings, 'KEEL_PRODUCT_NAME', ''),
                'product_url': product_url,
                'user_sub': user_sub,
                'items': [],
                'unread_notifications': [],
                'fetched_at': timezone.now().isoformat(),
            }
            cache.set(cache_key, payload, timeout=INBOX_CACHE_TTL_SECONDS)
            return JsonResponse(payload)

        try:
            payload = build_inbox_func(request, user)
        except Exception:
            logger.exception(
                'Error building helm inbox for user_sub=%s on %s',
                user_sub, request.path,
            )
            return JsonResponse({'error': 'Internal error building inbox.'}, status=500)

        if not payload.get('user_sub'):
            payload['user_sub'] = user_sub
        if not payload.get('fetched_at'):
            payload['fetched_at'] = timezone.now().isoformat()

        cache.set(cache_key, payload, timeout=INBOX_CACHE_TTL_SECONDS)
        return JsonResponse(payload)

    return wrapper


# ---------------------------------------------------------------------------
# Cross-product activity stream — companion to helm_feed_view + helm_inbox_view
#
# helm_feed_view: aggregate metrics + action items per product
# helm_inbox_view: per-user "awaiting me" items + unread notifications
# helm_activity_view: chronological keel.activity rows for the suite-wide
#                     "Across the suite" stream tab in Helm dashboard
#
# The endpoint returns the most recent N rows (default 50, max 200) optionally
# filtered by ``?since=<iso8601>`` for delta polls. Helm aggregates these
# across all peers, merges by created_at, and renders one chronological wall.
#
# Visibility: rows respect the per-product Activity.visible_to ACL implicitly
# because the endpoint is staff-token-only -- only the helm aggregator hits
# it, and helm renders the stream to staff users. For per-user filtering on
# the helm side (e.g. "show me activity I have access to across the suite"),
# Phase 2 will add a user_sub gate. v1 is staff-only.
# ---------------------------------------------------------------------------

ACTIVITY_CACHE_TTL_SECONDS = 60
ACTIVITY_DEFAULT_LIMIT = 50
ACTIVITY_MAX_LIMIT = 200


def _serialize_activity(activity) -> dict:
    """Render an Activity row to the cross-product wire shape.

    Mirrors AbstractActivity.render_for(user) but for cross-product transport,
    so includes target_type / target_id (string) for client-side grouping
    plus the wire-canonical metadata. Returns None for stub-tier rows; the
    caller filters those out (cross-product stub stripping is more conservative
    than per-record).
    """
    if activity.visibility == 'stub':
        return None
    return {
        'id': str(activity.pk),
        'verb': activity.verb,
        'actor_name': str(activity.actor) if activity.actor else 'system',
        'actor_id': str(activity.actor_id) if activity.actor_id else None,
        'source_label': activity.source_label or '',
        'deep_link': activity.deep_link or '',
        'target_type': activity.target_ct.model if activity.target_ct_id else '',
        'target_id': str(activity.target_id) if activity.target_id else '',
        'visibility': activity.visibility,
        'source_product': activity.source_product or '',
        'metadata': activity.metadata or {},
        'created_at': activity.created_at.isoformat(),
    }


def helm_activity_view(*, default_limit: int = ACTIVITY_DEFAULT_LIMIT):
    """Decorator factory for /api/v1/helm-feed/activity/ endpoints.

    Unlike helm_feed_view / helm_inbox_view, this decorator doesn't take a
    user-supplied builder -- the implementation is generic over any product's
    concrete Activity model. The wrapped factory call returns a ready-to-mount
    Django view.

    Usage:
        # product/api/helm_activity.py
        from keel.feed.views import helm_activity_view
        helm_activity = helm_activity_view()

        # product/urls.py
        path('api/v1/helm-feed/activity/', helm_activity, name='helm-feed-activity'),

    Query params:
        since=<iso8601>   -- only rows with created_at > since (delta polling)
        limit=<int>       -- override default_limit, capped at ACTIVITY_MAX_LIMIT

    Returns shape:
        {
            "product": "lookout",
            "product_label": "Lookout",
            "product_url": "https://lookout.docklabs.ai",
            "activities": [<serialized rows, newest first>],
            "fetched_at": "<iso>",
            "next_since": "<iso of newest row, for cursor-style polling>"
        }
    """
    from datetime import datetime as _datetime

    @csrf_exempt
    @require_GET
    def view(request):
        if not _accepted_keys(demo_mode=getattr(settings, 'DEMO_MODE', False)):
            return JsonResponse(
                {'error': 'Helm feed not configured (HELM_FEED_API_KEY missing).'},
                status=503,
            )

        matched = _authenticate_helm_bearer(request)
        if matched is None:
            return JsonResponse({'error': 'Invalid API key.'}, status=401)

        if _rate_limited(matched):
            return JsonResponse({'error': 'Rate limit exceeded.'}, status=429)

        # Parse since + limit
        since_str = (request.GET.get('since') or '').strip()
        since = None
        if since_str:
            try:
                since = _datetime.fromisoformat(since_str.replace('Z', '+00:00'))
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid `since` (use ISO 8601).'}, status=400,
                )

        try:
            limit = int(request.GET.get('limit') or default_limit)
        except (TypeError, ValueError):
            limit = default_limit
        limit = max(1, min(limit, ACTIVITY_MAX_LIMIT))

        # Cache key includes since + limit so deltas don't collide with full pulls
        cache_key = f'keel:helm_activity:{request.path}:{since_str}:{limit}'
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse(cached)

        # Resolve concrete Activity model
        from django.apps import apps as _apps
        activity_model_path = getattr(settings, 'KEEL_ACTIVITY_MODEL', '')
        if not activity_model_path:
            return JsonResponse(
                {'error': 'KEEL_ACTIVITY_MODEL not configured.'}, status=503,
            )
        try:
            Activity = _apps.get_model(activity_model_path)
        except LookupError:
            return JsonResponse(
                {'error': f'KEEL_ACTIVITY_MODEL={activity_model_path} not resolvable.'},
                status=503,
            )

        try:
            qs = (
                Activity.objects
                .select_related('actor', 'target_ct')
                .order_by('-created_at')
            )
            if since is not None:
                qs = qs.filter(created_at__gt=since)
            qs = qs[:limit]
            rows = [_serialize_activity(a) for a in qs]
            rows = [r for r in rows if r is not None]
        except Exception:
            logger.exception('Error building helm activity feed for %s', request.path)
            return JsonResponse(
                {'error': 'Internal error building activity feed.'}, status=500,
            )

        # Derive product metadata
        product_url = (
            getattr(settings, 'KEEL_PRODUCT_BASE_URL', '')
            or getattr(settings, 'KEEL_PRODUCT_URL', '')
            or request.build_absolute_uri('/').rstrip('/')
        )

        payload = {
            'product': getattr(settings, 'KEEL_PRODUCT_CODE', ''),
            'product_label': getattr(settings, 'KEEL_PRODUCT_NAME', ''),
            'product_url': product_url,
            'activities': rows,
            'fetched_at': timezone.now().isoformat(),
            'next_since': rows[0]['created_at'] if rows else (since_str or ''),
        }

        cache.set(cache_key, payload, timeout=ACTIVITY_CACHE_TTL_SECONDS)
        return JsonResponse(payload)

    return view
