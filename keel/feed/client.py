"""HTTP client for fetching helm feeds from products.

Used by Helm's ``fetch_feeds`` management command.
"""
import logging
import time

import requests

logger = logging.getLogger(__name__)

# Connection and read timeout (seconds)
DEFAULT_TIMEOUT = (5, 15)


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
