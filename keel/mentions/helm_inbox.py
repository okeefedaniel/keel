"""Helm cross-product inbox surface for @-mentions.

Each product that adopts ``keel.mentions`` wraps this ``build_inbox``
into its existing ``/api/v1/helm-feed/inbox/`` endpoint so the Helm
"Awaiting Me" column shows mentions alongside other inbox items.

Only user mentions surface here — Beacon contacts aren't Helm users and
have no inbox.
"""
from __future__ import annotations

import logging

from django.utils.timezone import now

from .models import MentionDelivery

logger = logging.getLogger(__name__)

_MAX_ITEMS = 25


def build_inbox_items(user) -> list[dict]:
    """Return up to 25 most-recent user MentionDelivery rows for ``user``.

    Each item conforms to the Helm UserInbox.items[] shape:

        {id, type='mention', title, deep_link, waiting_since,
         due_date, priority}

    Returns ``[]`` for anonymous users.
    """
    if not getattr(user, 'is_authenticated', False):
        return []

    rows = (
        MentionDelivery.objects
        .filter(
            recipient_kind=MentionDelivery.KIND_USER,
            recipient_user=user,
        )
        .select_related('note_content_type')
        .order_by('-delivered_at')[:_MAX_ITEMS]
    )

    out: list[dict] = []
    for row in rows:
        try:
            note = row.note  # Generic FK resolution
        except Exception:
            note = None

        title, deep_link = _title_and_link(note, row)
        out.append({
            'id': f'mention:{row.id}',
            'type': 'mention',
            'title': title,
            'deep_link': deep_link,
            'waiting_since': row.delivered_at.isoformat(),
            'due_date': None,
            'priority': 'medium',
        })
    return out


def _title_and_link(note, row) -> tuple[str, str]:
    """Best-effort title + deep link for a mention row. Gracefully degrades."""
    if note is None:
        return 'You were mentioned in a note (record removed)', ''

    # Derive a parent-record label + URL by walking common attribute names.
    parent_label = ''
    parent_url = ''
    for candidate in ('application', 'company', 'contact', 'invitation',
                      'opportunity', 'bill', 'program', 'project'):
        target = getattr(note, candidate, None)
        if target is not None:
            parent_label = str(target)
            try:
                parent_url = target.get_absolute_url() or ''
            except Exception:
                parent_url = ''
            break
    if not parent_label:
        parent_label = type(note).__name__
    title = f'Mentioned in {parent_label}'
    return title, parent_url
