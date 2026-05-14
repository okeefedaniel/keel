"""Keel-local 'audit feed' — direct ORM call against keel_audit_log.

Same response shape as a remote product's /api/v1/audit-feed/ so the
aggregator can treat keel and the sibling products uniformly.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Iterable

from django.db.models import Q
from django.utils import timezone

from keel.accounts.models import AuditLog

KEEL_LOCAL_LIMIT = 200


def fetch_keel_local(
    *,
    window_start: datetime,
    window_end: datetime,
    q: str = '',
    actions: Iterable[str] = (),
    limit: int = KEEL_LOCAL_LIMIT,
) -> dict:
    """Return Keel's own AuditLog slice in the cross-product shape."""
    start = time.monotonic()
    qs = AuditLog.objects.select_related('user').filter(
        timestamp__gte=window_start, timestamp__lte=window_end,
    ).order_by('-timestamp')
    action_list = [a for a in actions if a]
    if action_list:
        qs = qs.filter(action__in=action_list)
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
            'id': str(entry.id),
            'timestamp': entry.timestamp.isoformat(),
            'action': entry.action,
            'action_display': entry.get_action_display(),
            'entity_type': entry.entity_type,
            'entity_id': entry.entity_id,
            'description': entry.description,
            # Keel's concrete AuditLog has no deep_link_snapshot column
            # (the abstract has it, the concrete predates it). Future
            # migration could backfill; for now, empty string.
            'deep_link_snapshot': '',
            'ip_address': entry.ip_address,
            'user_username': entry.user.username if entry.user_id else '',
            'user_email': entry.user.email if entry.user_id else '',
            'product': 'keel',
        })
    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        'status': 'ok',
        'duration_ms': duration_ms,
        'data': {
            'items': rows,
            'total_in_window': total,
            'capped': total > limit,
            'window': [window_start.isoformat(), window_end.isoformat()],
            'fetched_at': timezone.now().isoformat(),
            'product': 'keel',
        },
        'error': '',
    }
