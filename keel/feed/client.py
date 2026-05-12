"""HTTP client for fetching helm feeds from products.

Used by Helm's ``fetch_feeds`` management command and by Keel's /audit/
cross-product aggregator.
"""
import logging
import time
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# Connection and read timeout (seconds)
DEFAULT_TIMEOUT = (5, 15)
AUDIT_DEFAULT_TIMEOUT = (5, 5)

# Module-level Session with a bumped connection pool so the 9-way fan-out
# from Keel's /audit/ page does not cold-start a TCP connection per product
# on every page render (review decision A7).
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
_session.mount('http://', _adapter)
_session.mount('https://', _adapter)


def fetch_product_feed(feed_url: str, api_key: str, timeout=DEFAULT_TIMEOUT) -> dict:
    """Fetch a single product's helm-feed endpoint.

    Returns a dict with keys:
        - ok (bool)
        - data (dict | None) — the feed payload on success
        - error (str) — error message on failure
        - duration_ms (int) — round-trip time
    """
    start = time.monotonic()
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    try:
        resp = requests.get(feed_url, headers=headers, timeout=timeout)
        duration_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code != 200:
            return {
                'ok': False,
                'data': None,
                'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                'duration_ms': duration_ms,
            }

        data = resp.json()
        return {
            'ok': True,
            'data': data,
            'error': '',
            'duration_ms': duration_ms,
        }

    except requests.ConnectionError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            'ok': False,
            'data': None,
            'error': f'Connection error: {e}',
            'duration_ms': duration_ms,
        }
    except requests.Timeout:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            'ok': False,
            'data': None,
            'error': f'Timeout after {timeout}s',
            'duration_ms': duration_ms,
        }
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            'ok': False,
            'data': None,
            'error': str(e),
            'duration_ms': duration_ms,
        }


def fetch_product_audit(
    feed_url: str,
    api_key: str,
    *,
    window_start: str,
    window_end: str,
    q: str = '',
    actions: Iterable[str] = (),
    limit: int = 200,
    timeout=AUDIT_DEFAULT_TIMEOUT,
) -> dict:
    """Fetch a single product's /api/v1/audit-feed/ endpoint.

    Unlike :func:`fetch_product_feed`, this returns a richer ``status`` enum
    so Keel's /audit/ aggregator can show a distinct status chip per product:

        ok            — 200 with valid JSON
        pending       — 404 (endpoint not mounted yet) or ConnectionError
                        (product unreachable). Renders as gray chip.
        unauthorized  — 401 / 403 (wrong API key on this service)
        timeout       — read timeout
        error         — 5xx, JSONDecodeError, or anything else unexpected

    Returns::

        {
            'status': <one of the above>,
            'data': <feed payload> | None,
            'error': <str>,
            'duration_ms': <int>,
        }

    Query params (window_start, window_end, q, actions, limit) are sent as
    ISO-8601 strings / comma-joined lists / int. The product's
    ``audit_feed_view`` decorator includes the full query string in its
    cache key.
    """
    start = time.monotonic()
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    params = {
        'window_start': window_start,
        'window_end': window_end,
        'limit': str(limit),
    }
    if q:
        params['q'] = q
    actions_list = [a for a in actions if a]
    if actions_list:
        params['actions'] = ','.join(actions_list)

    try:
        resp = _session.get(feed_url, headers=headers, params=params, timeout=timeout)
        duration_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError as e:
                return {
                    'status': 'error',
                    'data': None,
                    'error': f'Malformed JSON: {e}',
                    'duration_ms': duration_ms,
                }
            return {
                'status': 'ok',
                'data': data,
                'error': '',
                'duration_ms': duration_ms,
            }

        if resp.status_code == 404:
            return {
                'status': 'pending',
                'data': None,
                'error': 'Endpoint not mounted (HTTP 404)',
                'duration_ms': duration_ms,
            }

        if resp.status_code in (401, 403):
            return {
                'status': 'unauthorized',
                'data': None,
                'error': f'HTTP {resp.status_code}',
                'duration_ms': duration_ms,
            }

        return {
            'status': 'error',
            'data': None,
            'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
            'duration_ms': duration_ms,
        }

    except requests.ConnectionError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            'status': 'pending',
            'data': None,
            'error': f'Connection error: {e}',
            'duration_ms': duration_ms,
        }
    except requests.Timeout:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            'status': 'timeout',
            'data': None,
            'error': f'Timeout after {timeout}s',
            'duration_ms': duration_ms,
        }
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            'status': 'error',
            'data': None,
            'error': str(e),
            'duration_ms': duration_ms,
        }
