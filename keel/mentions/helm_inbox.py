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
    """Best-effort title + deep link for a mention row. Gracefully degrades.

    Resolution order:

    1. ``note.get_mention_parent()`` if the note model defines it. Return shape:
       a single parent object whose ``str()`` is the label and whose
       ``get_absolute_url()`` is the link. This is the override hook for
       products that have ambiguous FKs (e.g., a note with both
       ``application`` and ``contact`` FKs).
    2. Fallback: walk a fixed list of common parent attribute names. This is
       a best-effort heuristic — when the order matters, define
       ``get_mention_parent()``.
    """
    if note is None:
        return 'You were mentioned in a note (record removed)', ''

    # Override hook
    parent = None
    if hasattr(note, 'get_mention_parent'):
        try:
            parent = note.get_mention_parent()
        except Exception:
            parent = None

    if parent is None:
        # Fallback heuristic — walk common parent attribute names.
        for candidate in ('application', 'company', 'contact', 'invitation',
                          'opportunity', 'bill', 'program', 'project'):
            target = getattr(note, candidate, None)
            if target is not None:
                parent = target
                break

    parent_label = ''
    parent_url = ''
    if parent is not None:
        parent_label = str(parent)
        try:
            parent_url = parent.get_absolute_url() or ''
        except Exception:
            parent_url = ''
    if not parent_label:
        parent_label = type(note).__name__
    title = f'Mentioned in {parent_label}'
    return title, parent_url
