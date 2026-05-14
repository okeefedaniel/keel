"""Outbound client for Beacon contact-mention provenance.

Mirrors the keel.signatures.client pattern: best-effort cross-product
POST/GET; gracefully returns empty/False on any failure so the caller's
local action (saving a note) never fails because Beacon is down.

Three entry points:

    is_available()
        True when BEACON_INTAKE_URL + BEACON_INTAKE_API_KEY are both set.

    search_contacts(q, requester)
    search_contacts_by_slugs(slugs, requester)
        GET https://<beacon>/api/v1/contacts/lookup/
        Returns a list of {slug, display_name, organization, url} dicts,
        or [] on any failure.

    append_contact_mention(contact_slug, *, source_product, source_url,
                            source_label, author_username, excerpt)
        POST https://<beacon>/api/v1/intake/contact-mentions/
        Returns True on 2xx, False on any other outcome. Never raises.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

# Timeouts (seconds). Conservative — these are user-facing form posts.
_LOOKUP_TIMEOUT = 2
_INTAKE_TIMEOUT = 5


def is_available() -> bool:
    """True when Beacon is configured for this deployment."""
    return bool(
        getattr(settings, 'BEACON_INTAKE_URL', '')
        and getattr(settings, 'BEACON_INTAKE_API_KEY', '')
    )


def _headers() -> dict[str, str]:
    return {
        'Authorization': f'Bearer {settings.BEACON_INTAKE_API_KEY}',
        'Accept': 'application/json',
    }


def _base() -> str:
    return settings.BEACON_INTAKE_URL.rstrip('/')


def _http():
    """Lazy import of requests — only needed when Beacon is reachable."""
    import requests  # noqa: WPS433 — lazy import is intentional
    return requests


def search_contacts(q: str, requester: Any = None) -> list[dict]:
    """Free-text search of Beacon contacts for the picker autocomplete.

    Sends ``?q=<query>&actor=<username>`` so Beacon can apply its own
    org/access scoping based on the calling user's identity.
    """
    if not is_available():
        return []
    if not q or len(q) < 2:
        return []

    try:
        requests = _http()
        actor = getattr(requester, 'username', '') if requester is not None else ''
        resp = requests.get(
            f'{_base()}/api/v1/contacts/lookup/',
            params={'q': q, 'actor': actor},
            headers=_headers(),
            timeout=_LOOKUP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get('results', [])
        return list(data)[:25] if isinstance(data, list) else []
    except Exception as exc:
        logger.info(
            'mentions.beacon.search_contacts: cross.peer_unreachable q=%r exc=%s',
            q, exc,
        )
        return []


def search_contacts_by_slugs(slugs: list[str], requester: Any = None) -> list[dict]:
    """Resolve an explicit list of slugs to contact metadata.

    Used by parser.resolve_contacts after parsing ``@beacon:slug`` tokens.
    """
    if not is_available() or not slugs:
        return []

    try:
        requests = _http()
        actor = getattr(requester, 'username', '') if requester is not None else ''
        resp = requests.get(
            f'{_base()}/api/v1/contacts/lookup/',
            params={'slugs': ','.join(slugs), 'actor': actor},
            headers=_headers(),
            timeout=_LOOKUP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get('results', [])
        return list(data) if isinstance(data, list) else []
    except Exception as exc:
        logger.info(
            'mentions.beacon.search_contacts_by_slugs: cross.peer_unreachable exc=%s',
            exc,
        )
        return []


def append_contact_mention(
    contact_slug: str,
    *,
    source_product: str,
    source_url: str,
    source_label: str,
    author_username: str,
    excerpt: str,
) -> tuple[bool, str]:
    """Append a contact-mention provenance row + ContactNote on Beacon.

    Returns ``(ok, error)``. On 2xx: ``(True, '')``. On any other outcome:
    ``(False, <truncated error message>)``. Never raises.

    Caller (notify.dispatch_mentions) persists the result onto the
    MentionDelivery row's ``peer_status`` / ``peer_error`` fields.
    """
    if not is_available():
        return False, 'beacon not configured'

    payload = {
        'contact_slug': contact_slug,
        'source_product': source_product,
        'source_url': source_url,
        'source_label': source_label,
        'author_username': author_username,
        'excerpt': excerpt[:500],
    }

    try:
        requests = _http()
        resp = requests.post(
            f'{_base()}/api/v1/intake/contact-mentions/',
            json=payload,
            headers={**_headers(), 'Content-Type': 'application/json'},
            timeout=_INTAKE_TIMEOUT,
        )
        if 200 <= resp.status_code < 300:
            return True, ''
        if resp.status_code == 410:
            return False, 'gone'
        return False, f'http {resp.status_code}: {resp.text[:200]}'
    except Exception as exc:
        logger.warning(
            'mentions.beacon.append_contact_mention failed: slug=%s exc=%s',
            contact_slug, exc,
        )
        return False, str(exc)[:500]
