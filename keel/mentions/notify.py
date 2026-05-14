"""Dispatch @-mention notifications and cross-product writes.

Called by ``MentionFormMixin._save_m2m()`` after the note row has been
saved and the ``mentions`` M2M written. Two paths:

- User mention: ``MentionDelivery.objects.get_or_create`` on
  ``(note, user)``; if created, dispatch via ``keel.notifications.notify``.

- Contact mention: ``MentionDelivery.objects.get_or_create`` on
  ``(note, beacon_contact_slug)``; if created, best-effort POST to
  Beacon. Local row stays regardless — peer_status records the outcome
  for a later retry job.

Idempotency is anchored on ``MentionDelivery``'s unique constraints, NOT
on ``transaction.atomic`` + ``select_for_update`` (which is a leaky
guarantee that depends on per-request atomic blocks not all products use).
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction

from keel.notifications.dispatch import notify

from .beacon import append_contact_mention
from .models import MentionDelivery

logger = logging.getLogger(__name__)


def _excerpt_for(text: str, max_chars: int = 280) -> str:
    """Truncate note content for email subject / Beacon excerpt."""
    text = (text or '').strip().replace('\n', ' ')
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + '…'


def dispatch_mentions(
    *,
    note,
    added_users: Iterable,
    added_contacts: Iterable[dict],
    source_obj,
    source_url: str,
    source_label: str,
    source_product: str,
    author=None,
) -> dict:
    """Fire mention notifications for newly added recipients.

    Args:
        note: The saved note instance (the ``mentions`` M2M has already been
            written before this is called).
        added_users: Iterable of KeelUser instances newly added in this save.
        added_contacts: Iterable of contact dicts with at least ``slug``,
            ``display_name``, ``url``.
        source_obj: The parent record (e.g., the Harbor Application).
        source_url: Absolute URL to view the parent record.
        source_label: Human-readable label of the parent record.
        source_product: Current product code (lowercase, e.g. 'harbor').
        author: The user who wrote the note (for notify actor + Beacon body).

    Returns:
        dict with counts: ``{'users_notified', 'contacts_attempted',
        'contacts_ok', 'contacts_failed'}``.
    """
    note_ct = ContentType.objects.get_for_model(type(note))
    excerpt = _excerpt_for(getattr(note, 'content', ''))
    author_name = (
        author.get_full_name() if author and author.get_full_name()
        else getattr(author, 'username', 'A teammate') if author
        else 'A teammate'
    )
    author_username = getattr(author, 'username', '') if author else ''

    summary = {
        'users_notified': 0,
        'contacts_attempted': 0,
        'contacts_ok': 0,
        'contacts_failed': 0,
    }

    # --- User mentions ----------------------------------------------------
    for user in added_users:
        delivery, created = _create_user_delivery(
            note_ct=note_ct, note_pk=note.pk, user=user,
        )
        if not created:
            continue  # already delivered for this (note, user)
        try:
            notify(
                event='note_mentioned',
                actor=author,
                recipients=[user],
                context={
                    'actor': author,
                    'actor_name': author_name,
                    'note': note,
                    'note_excerpt': excerpt,
                    'record_title': source_label,
                    'source_url': source_url,
                    'source_product': source_product,
                    'source_obj': source_obj,
                    'note_id': str(note.pk),
                },
                link=source_url,
            )
            summary['users_notified'] += 1
        except Exception:
            logger.exception(
                'dispatch_mentions: notify() raised for user=%s note=%s',
                user.pk, note.pk,
            )

    # --- Contact mentions -------------------------------------------------
    for contact in added_contacts:
        slug = contact.get('slug')
        if not slug:
            continue
        delivery, created = _create_contact_delivery(
            note_ct=note_ct,
            note_pk=note.pk,
            slug=slug,
            peer_url=contact.get('url', ''),
        )
        if not created:
            continue  # already delivered for this (note, contact)
        summary['contacts_attempted'] += 1
        ok, error = append_contact_mention(
            slug,
            source_product=source_product,
            source_url=source_url,
            source_label=source_label,
            author_username=author_username,
            excerpt=excerpt,
        )
        delivery.peer_status = (
            MentionDelivery.PEER_OK if ok
            else MentionDelivery.PEER_GONE if error == 'gone'
            else MentionDelivery.PEER_FAILED
        )
        delivery.peer_error = '' if ok else error
        delivery.save(update_fields=['peer_status', 'peer_error'])
        if ok:
            summary['contacts_ok'] += 1
        else:
            summary['contacts_failed'] += 1

    return summary


def _create_user_delivery(*, note_ct, note_pk, user):
    """Get-or-create a user delivery row. Returns (row, created)."""
    try:
        with transaction.atomic():
            return MentionDelivery.objects.get_or_create(
                note_content_type=note_ct,
                note_object_id=note_pk,
                recipient_kind=MentionDelivery.KIND_USER,
                recipient_user=user,
                defaults={'recipient_ref': ''},
            )
    except IntegrityError:
        # Concurrent insert from another save — fetch the existing row.
        existing = MentionDelivery.objects.get(
            note_content_type=note_ct,
            note_object_id=note_pk,
            recipient_kind=MentionDelivery.KIND_USER,
            recipient_user=user,
        )
        return existing, False


def _create_contact_delivery(*, note_ct, note_pk, slug, peer_url):
    """Get-or-create a contact delivery row. Returns (row, created)."""
    try:
        with transaction.atomic():
            return MentionDelivery.objects.get_or_create(
                note_content_type=note_ct,
                note_object_id=note_pk,
                recipient_kind=MentionDelivery.KIND_CONTACT,
                recipient_ref=slug,
                defaults={'recipient_peer_url': peer_url},
            )
    except IntegrityError:
        existing = MentionDelivery.objects.get(
            note_content_type=note_ct,
            note_object_id=note_pk,
            recipient_kind=MentionDelivery.KIND_CONTACT,
            recipient_ref=slug,
        )
        return existing, False
