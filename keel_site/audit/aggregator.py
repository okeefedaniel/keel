"""Cross-product audit aggregator.

Keel's /audit/ page fans out via this module: parallel HTTP fetches against
each sibling product's /api/v1/audit-feed/ endpoint, plus a direct ORM
call against Keel's own audit log. Results merge by ``timestamp`` (desc).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

from keel.feed.client import fetch_product_audit

from .keel_local import fetch_keel_local

AUDIT_PER_PRODUCT_LIMIT = 200
AUDIT_FETCH_TIMEOUT = (5, 5)


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
    def security_event_count(self) -> int:
        return sum(1 for r in self.rows if r.get('action') == 'security_event')


def _audit_feed_url_for(product_url: str) -> str:
    """Derive https://{host}/api/v1/audit-feed/ from a fleet entry's URL."""
    parts = urlsplit(product_url)
    return urlunsplit((parts.scheme, parts.netloc, '/api/v1/audit-feed/', '', ''))


def _api_key() -> str:
    return getattr(settings, 'HELM_FEED_API_KEY', '') or ''


def aggregate_audit(
    *,
    visible_products: list[str],
    window_start: datetime,
    window_end: datetime,
    q: str = '',
    actions: Iterable[str] = (),
    limit: int = AUDIT_PER_PRODUCT_LIMIT,
) -> AggregateResult:
    """Fan out to each visible product, merge, return."""
    fleet = {p['code']: p for p in getattr(settings, 'KEEL_FLEET_PRODUCTS', [])}
    api_key = _api_key()
    result = AggregateResult(window_start=window_start, window_end=window_end)

    if not visible_products:
        return result

    iso_start = window_start.isoformat()
    iso_end = window_end.isoformat()
    actions_tuple = tuple(actions)

    def _fetch_remote(code: str) -> tuple[str, dict]:
        entry = fleet.get(code)
        if entry is None:
            return code, {
                'status': 'error', 'duration_ms': 0, 'data': None,
                'error': f'No KEEL_FLEET_PRODUCTS entry for {code}',
            }
        url = _audit_feed_url_for(entry['url'])
        return code, fetch_product_audit(
            url, api_key,
            window_start=iso_start, window_end=iso_end,
            q=q, actions=actions_tuple, limit=limit, timeout=AUDIT_FETCH_TIMEOUT,
        )

    def _fetch_local() -> tuple[str, dict]:
        return 'keel', fetch_keel_local(
            window_start=window_start, window_end=window_end,
            q=q, actions=actions_tuple, limit=limit,
        )

    with ThreadPoolExecutor(max_workers=min(10, max(1, len(visible_products)))) as ex:
        futures = []
        for code in visible_products:
            if code == 'keel':
                futures.append(ex.submit(_fetch_local))
            else:
                futures.append(ex.submit(_fetch_remote, code))
        for fut in futures:
            code, fetch = fut.result()
            data = fetch.get('data') or {}
            items = data.get('items') or []
            capped = bool(data.get('capped'))
            total = int(data.get('total_in_window') or 0)
            result.per_product[code] = ProductStatus(
                product=code,
                status=fetch.get('status', 'error'),
                duration_ms=int(fetch.get('duration_ms') or 0),
                capped=capped,
                total_in_window=total,
                error=fetch.get('error', '') or '',
            )
            for row in items:
                row.setdefault('product', code)
                result.rows.append(row)

    result.rows.sort(key=lambda r: r.get('timestamp', ''), reverse=True)
    return result
