"""Cross-product activity aggregator for /ops/ Row 2 (system-events lane).

Fans out parallel HTTP fetches to each visible product's
`/api/v1/activity-feed/` endpoint, filtered to `status` and `verbs`. Results
merge by `timestamp` (desc). Product-level errors degrade gracefully — a 404
renders as a "pending" chip (product hasn't mounted the endpoint yet);
401/403 renders "unauthorized"; timeouts render "timeout".

Mirrors keel_site.audit.aggregator.aggregate_audit so the two pages look and
feel the same. Distinct module so the contracts can evolve independently.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

from keel.feed.client import fetch_product_activity

ACTIVITY_PER_PRODUCT_LIMIT = 200
ACTIVITY_FETCH_TIMEOUT = (5, 5)


@dataclass
class ProductStatus:
    product: str
    status: str  # 'ok' | 'pending' | 'unauthorized' | 'timeout' | 'error'
    duration_ms: int = 0
    capped: bool = False
    total_in_window: int = 0
    error: str = ''


@dataclass
class AggregateResult:
    rows: list[dict] = field(default_factory=list)
    per_product: dict[str, ProductStatus] = field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None

    @property
    def failure_count(self) -> int:
        """How many Activity rows in the window are flagged failed/errored?

        Drives the page header's red badge when non-zero — staff scanning
        /ops/ should see "5 failures in this window" before they read rows.
        """
        return sum(1 for r in self.rows
                   if r.get('status') in ('failed', 'errored'))

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.rows if r.get('status') == 'warn')


def _activity_feed_url_for(product_url: str) -> str:
    """Derive https://{host}/api/v1/activity-feed/ from a fleet entry's URL."""
    parts = urlsplit(product_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, '/api/v1/activity-feed/', '', '')
    )


def _api_key() -> str:
    return getattr(settings, 'HELM_FEED_API_KEY', '') or ''


def aggregate_activity(
    *,
    visible_products: list[str],
    window_start: datetime,
    window_end: datetime,
    q: str = '',
    verbs: Iterable[str] = (),
    status: str = 'any',
    limit: int = ACTIVITY_PER_PRODUCT_LIMIT,
) -> AggregateResult:
    """Fan out to each visible product, merge their activity-feed responses.

    Each product gets fetched concurrently (ThreadPoolExecutor). A product
    with no `/api/v1/activity-feed/` mounted returns status='pending' and
    its rows are absent from the merged list — that's the visible signal
    on /ops/ that this product needs the endpoint wired (finding F1 in the
    2026-06-27 review).
    """
    fleet = {p['code']: p for p in getattr(settings, 'KEEL_FLEET_PRODUCTS', [])}
    api_key = _api_key()
    result = AggregateResult(window_start=window_start, window_end=window_end)

    if not visible_products:
        return result

    iso_start = window_start.isoformat()
    iso_end = window_end.isoformat()
    verbs_tuple = tuple(verbs)

    def _fetch_remote(code: str) -> tuple[str, dict]:
        entry = fleet.get(code)
        if entry is None:
            return code, {
                'status': 'pending', 'data': None,
                'error': f'product {code!r} not in KEEL_FLEET_PRODUCTS',
                'duration_ms': 0,
            }
        feed_url = _activity_feed_url_for(entry['url'])
        return code, fetch_product_activity(
            feed_url, api_key,
            window_start=iso_start, window_end=iso_end,
            q=q, verbs=verbs_tuple, status=status, limit=limit,
            timeout=ACTIVITY_FETCH_TIMEOUT,
        )

    # ThreadPoolExecutor — same pattern as audit aggregator. Each product
    # waits on a 5s connect + 5s read timeout independently.
    with ThreadPoolExecutor(max_workers=min(10, len(visible_products))) as pool:
        for code, resp in pool.map(_fetch_remote, visible_products):
            duration_ms = resp.get('duration_ms', 0)
            data = resp.get('data') or {}
            items = data.get('items', []) or []
            result.per_product[code] = ProductStatus(
                product=code,
                status=resp.get('status', 'error'),
                duration_ms=duration_ms,
                capped=bool(data.get('capped')),
                total_in_window=int(data.get('total_in_window', 0)),
                error=resp.get('error', ''),
            )
            # Annotate every row with the product code so the merged list
            # knows where each row came from when product isn't already set.
            for row in items:
                if not row.get('product'):
                    row['product'] = code
                result.rows.append(row)

    # Sort by timestamp desc — most recent first. Stable across products.
    result.rows.sort(key=lambda r: r.get('timestamp', ''), reverse=True)
    return result
