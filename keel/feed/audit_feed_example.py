"""Reference implementation of /api/v1/audit-feed/ for sibling products.

Each sibling product (admiralty, beacon, bounty, harbor, helm, lookout,
manifest, purser, yeoman) should copy this file into its own
``<product>/api/audit_feed.py`` and adjust the AuditLog import. The
``@audit_feed_view`` decorator handles bearer auth, rate limiting, and
per-query-param caching.

Per-product rollout checklist:

1. Copy this file to ``<product>/api/audit_feed.py`` (or your equivalent
   API package).
2. Replace the ``from <product>.core.models import AuditLog`` line with
   the concrete AuditLog class in this product.
3. Wire the URL in your product's urls.py::

        from <product>.api.audit_feed import build_audit
        path('api/v1/audit-feed/', build_audit, name='audit-feed'),

4. Bump ``keel`` in requirements.txt to ``>=0.38.0`` (gets the
   ``audit_feed_view`` decorator + ``fetch_product_audit`` client).
5. Smoke test the live endpoint::

        curl -H "Authorization: Bearer $HELM_FEED_API_KEY" \\
             "https://<product>.docklabs.ai/api/v1/audit-feed/?window_start=2026-05-12T00:00:00&window_end=2026-05-12T01:00:00&limit=10"

6. Deploy and confirm Keel's /audit/ page chip flips from gray "pending"
   to green "ok" for this product.

The response shape MUST match (keel.feed.audit_feed_view normalizes
``fetched_at`` and ``product`` if missing). Use ``description__icontains``
keyword search and apply the action filter inside the SQL query — never
after the row cap, or rare-action results get silently truncated.
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.conf import settings
from django.db.models import Q
from django.utils import timezone as dj_tz

from keel.feed import audit_feed_view

# ---- Replace this import for the concrete product ------------------------
# Each product subclasses keel.core.models.AbstractAuditLog into its own
# concrete table. Point this at the right one.
#
# Examples:
#   from harbor.core.models import AuditLog
#   from beacon.companies.models import AuditLog
#   from helm.dashboard.models import AuditLog
from beacon.companies.models import AuditLog  # <-- EDIT THIS LINE


def _parse_iso(value: str | None, default: datetime) -> datetime:
    """Parse an ISO-8601 string; fall back to ``default`` on missing/invalid."""
    if not value:
        return default
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return default
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@audit_feed_view
def build_audit(request):
    now = dj_tz.now()
    window_start = _parse_iso(request.GET.get('window_start'), now)
    window_end = _parse_iso(request.GET.get('window_end'), now)
    q = (request.GET.get('q') or '').strip()
    actions = [a for a in (request.GET.get('actions') or '').split(',') if a]
    try:
        limit = int(request.GET.get('limit') or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 200))

    qs = AuditLog.objects.select_related('user').filter(
        timestamp__gte=window_start, timestamp__lte=window_end,
    ).order_by('-timestamp')

    # Action filter applied BEFORE the cap (review decision A6) so a
    # rare-action filter does not silently truncate.
    if actions:
        qs = qs.filter(action__in=actions)

    if q:
        qs = qs.filter(
            Q(description__icontains=q)
            | Q(entity_type__icontains=q)
            | Q(entity_id__icontains=q)
            | Q(user__username__icontains=q)
            | Q(user__email__icontains=q),
        )

    total = qs.count()
    rows = []
    for entry in qs[:limit]:
        rows.append({
            'id': str(entry.id) if entry.id is not None else '',
            'timestamp': entry.timestamp.isoformat(),
            'action': entry.action,
            'action_display': entry.get_action_display(),
            'entity_type': entry.entity_type,
            'entity_id': entry.entity_id,
            'description': entry.description or '',
            'deep_link_snapshot': getattr(entry, 'deep_link_snapshot', '') or '',
            'ip_address': entry.ip_address,
            'user_username': entry.user.username if entry.user_id else '',
            'user_email': entry.user.email if entry.user_id else '',
            'product': getattr(settings, 'KEEL_PRODUCT_CODE', '') or
                       getattr(settings, 'KEEL_PRODUCT_NAME', '').lower(),
        })

    return {
        'items': rows,
        'total_in_window': total,
        'capped': total > limit,
        'window': [window_start.isoformat(), window_end.isoformat()],
        'fetched_at': dj_tz.now().isoformat(),
        'product': getattr(settings, 'KEEL_PRODUCT_CODE', '') or
                   getattr(settings, 'KEEL_PRODUCT_NAME', '').lower(),
    }
