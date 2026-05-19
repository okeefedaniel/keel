"""Reference implementation of /api/v1/activity-feed/ for sibling products.

Each product copies this file into its own ``<product>/api/activity_feed.py``
and adjusts the ``Activity`` import. The ``@activity_feed_view`` decorator
handles bearer auth, rate limiting, and per-query-param caching.

Per-product rollout checklist:

1. Copy this file to ``<product>/api/activity_feed.py``.
2. Replace the import to point at this product's concrete ``Activity`` subclass
   (e.g. ``from helm.tasks.models import Activity``,
   ``from beacon.companies.models import ContactActivity``).
3. Wire the URL in your product's urls.py::

        from <product>.api.activity_feed import build_activity
        path('api/v1/activity-feed/', build_activity, name='activity-feed'),

4. Bump ``keel`` in requirements.txt to ``>=0.47.1`` (gets the
   ``activity_feed_view`` decorator + ``fetch_product_activity`` client).
5. Smoke test::

        curl -H "Authorization: Bearer $HELM_FEED_API_KEY" \\
             "https://<product>.docklabs.ai/api/v1/activity-feed/?\
window_start=2026-05-19T00:00:00&window_end=2026-05-19T01:00:00&limit=10"

6. Deploy and confirm Keel's ``/ops/`` Row 2 chip flips from gray "pending"
   to green "ok" for this product.

The response shape MUST match (keel.feed.activity_feed_view normalizes
``fetched_at`` and ``product`` if missing). Apply ``verbs`` / ``status``
filters inside the SQL query — never after the row cap, or rare-event
results get silently truncated.
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.db.models import Q
from django.utils import timezone as dj_tz

from keel.core.utils import get_product_code
from keel.feed import activity_feed_view

# ---- Replace this import for the concrete product -----------------------
# Each product subclasses keel.activity.models.AbstractActivity into its
# own concrete table. Point this at the right one.
#
# Examples:
#   from helm.tasks.models import Activity
#   from beacon.companies.models import ContactActivity
#   from harbor.applications.models import ApplicationActivity
from beacon.companies.models import Activity  # <-- EDIT THIS LINE


def _parse_iso(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return default
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@activity_feed_view
def build_activity(request):
    now = dj_tz.now()
    window_start = _parse_iso(request.GET.get('window_start'), now)
    window_end = _parse_iso(request.GET.get('window_end'), now)
    q = (request.GET.get('q') or '').strip()
    verbs = [v for v in (request.GET.get('verbs') or '').split(',') if v]
    status = (request.GET.get('status') or 'any').strip().lower()
    try:
        limit = int(request.GET.get('limit') or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 200))

    qs = Activity.objects.select_related('actor').filter(
        created_at__gte=window_start, created_at__lte=window_end,
    ).order_by('-created_at')

    # Filters applied BEFORE the cap so rare-verb / rare-status results
    # don't get silently truncated.
    if verbs:
        qs = qs.filter(verb__in=verbs)
    if status != 'any':
        # status lives in metadata JSON. Postgres JSONB supports ->> directly;
        # SQLite test runs use JSON1 with the same operator. Both honor the
        # JSON-typed comparison.
        qs = qs.filter(metadata__status=status)
    if q:
        qs = qs.filter(
            Q(source_label__icontains=q)
            | Q(verb__icontains=q)
            | Q(actor__username__icontains=q),
        )

    total = qs.count()
    rows = []
    for entry in qs[:limit]:
        rows.append({
            'id': str(entry.id),
            'timestamp': entry.created_at.isoformat(),
            'verb': entry.verb,
            'summary': entry.source_label or '',
            'status': (entry.metadata or {}).get('status', 'ok'),
            'actor_username': entry.actor.username if entry.actor_id else '',
            'target_type': entry.target_ct.model if entry.target_ct_id else '',
            'target_id': entry.target_id or '',
            'visibility': entry.visibility,
            'deep_link': entry.deep_link or '',
            'metadata': entry.metadata or {},
            'product': get_product_code(),
        })

    return {
        'items': rows,
        'total_in_window': total,
        'capped': total > limit,
        'window': [window_start.isoformat(), window_end.isoformat()],
        'fetched_at': dj_tz.now().isoformat(),
        'product': get_product_code(),
    }
