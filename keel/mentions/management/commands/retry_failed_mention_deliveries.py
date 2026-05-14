"""``manage.py retry_failed_mention_deliveries``

Retries cross-product Beacon contact-mention writes that failed at
the original dispatch time. Reads every ``MentionDelivery`` row with
``peer_status='failed'`` and replays the Beacon POST. On success the
row's ``peer_status`` flips to ``ok``; on persistent failure the
``peer_error`` is refreshed with the latest reason.

Beacon-side idempotency keys on ``(contact_slug, source_url)`` so a
retry NEVER double-writes the same provenance row, even if the
original attempt actually succeeded but the response was dropped.

Intended cadence: run as a daily cron (or after restoring Beacon
connectivity). Safe to run repeatedly — no side effects on already-OK
or already-gone rows.

Exit codes:
- 0 — succeeded (zero failed rows OR all retries processed)
- 1 — runtime error before retry loop could start
"""
from __future__ import annotations

import logging
from contextlib import suppress

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from keel.mentions.beacon import append_contact_mention, is_available
from keel.mentions.models import MentionDelivery
from keel.mentions.notify import _excerpt_for

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Retry MentionDelivery rows with peer_status=failed. '
        'Best-effort cross-product POST to Beacon; updates peer_status '
        'in place. Idempotent.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=100,
            help=(
                'Max number of rows to retry in a single run (default 100). '
                'Prevents long-running batches; re-run to drain a large queue.'
            ),
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List what would be retried without calling Beacon.',
        )
        parser.add_argument(
            '--include-gone', action='store_true',
            help=(
                'Also retry rows with peer_status=gone (Beacon previously '
                "returned 410). Default skips them — they typically mean "
                "the contact was deleted on the Beacon side and won't recover."
            ),
        )

    def handle(self, *args, **options):
        limit = options['limit']
        dry_run = options['dry_run']
        include_gone = options['include_gone']

        if not is_available():
            self.stderr.write(self.style.ERROR(
                'Beacon is not configured (BEACON_INTAKE_URL / '
                'BEACON_INTAKE_API_KEY missing). Cannot retry.'
            ))
            return

        # Pull only contact-mention rows in failed (or optionally gone) state.
        statuses = [MentionDelivery.PEER_FAILED]
        if include_gone:
            statuses.append(MentionDelivery.PEER_GONE)

        qs = (
            MentionDelivery.objects
            .filter(
                recipient_kind=MentionDelivery.KIND_CONTACT,
                peer_status__in=statuses,
            )
            .order_by('delivered_at')[:limit]
        )

        rows = list(qs)
        total = len(rows)
        if total == 0:
            self.stdout.write(self.style.SUCCESS(
                'No failed contact mentions to retry.'
            ))
            return

        self.stdout.write(self.style.WARNING(
            f'Found {total} failed contact mention(s) to retry'
            + (' (--include-gone)' if include_gone else '')
            + (' — dry-run, no requests will be sent' if dry_run else '')
            + '.'
        ))

        ok_count = 0
        failed_count = 0
        gone_count = 0

        for row in rows:
            note = self._resolve_note(row)
            if note is None:
                self.stderr.write(self.style.WARNING(
                    f'  SKIP {row.id} — source note no longer exists '
                    f'(contact_slug={row.recipient_ref}, '
                    f'source_url={_short(row.recipient_peer_url)})'
                ))
                continue

            source = self._resolve_source(note)
            author = getattr(note, 'author', None)
            payload = {
                'contact_slug': row.recipient_ref,
                'source_product': self._guess_product_code(source, note),
                'source_url': row.recipient_peer_url,
                'source_label': str(source) if source is not None else str(note),
                'author_username': getattr(author, 'username', '') if author else '',
                'excerpt': _excerpt_for(getattr(note, 'content', '')),
            }

            if dry_run:
                self.stdout.write(
                    f'  WOULD retry {row.id} (contact={row.recipient_ref}, '
                    f'product={payload["source_product"]})'
                )
                continue

            ok, error = append_contact_mention(
                row.recipient_ref,
                source_product=payload['source_product'],
                source_url=payload['source_url'],
                source_label=payload['source_label'],
                author_username=payload['author_username'],
                excerpt=payload['excerpt'],
            )
            if ok:
                new_status = MentionDelivery.PEER_OK
                ok_count += 1
                marker = self.style.SUCCESS('  OK   ')
            elif error == 'gone':
                new_status = MentionDelivery.PEER_GONE
                gone_count += 1
                marker = self.style.WARNING('  GONE ')
            else:
                new_status = MentionDelivery.PEER_FAILED
                failed_count += 1
                marker = self.style.ERROR('  FAIL ')

            with transaction.atomic():
                # update() avoids a race against another retry process that
                # might be touching the same row.
                MentionDelivery.objects.filter(pk=row.pk).update(
                    peer_status=new_status,
                    peer_error='' if ok else (error or 'unknown'),
                )

            self.stdout.write(
                f'{marker}{row.id} contact={row.recipient_ref} '
                f'product={payload["source_product"]}'
                + (f' — {error}' if not ok and error else '')
            )

        summary = (
            f'\nRetry complete: {ok_count} ok, {failed_count} failed, '
            f'{gone_count} gone (of {total} attempted).'
        )
        if failed_count == 0 and gone_count == 0:
            self.stdout.write(self.style.SUCCESS(summary))
        else:
            self.stdout.write(self.style.WARNING(summary))

    def _resolve_note(self, row: MentionDelivery):
        """Return the source note instance, or None if it's been deleted."""
        try:
            ct = ContentType.objects.get_for_id(row.note_content_type_id)
        except ContentType.DoesNotExist:
            return None
        Model = ct.model_class()
        if Model is None:
            return None
        with suppress(Model.DoesNotExist):
            return Model.objects.get(pk=row.note_object_id)
        return None

    def _resolve_source(self, note):
        """Best-effort: find the parent record the note hangs off.

        Mirrors keel.mentions.helm_inbox._title_and_link's resolution
        order: ``get_mention_parent()`` hook first, then a walk over
        common FK names. Falls back to the note itself.
        """
        if hasattr(note, 'get_mention_parent'):
            with suppress(Exception):
                parent = note.get_mention_parent()
                if parent is not None:
                    return parent
        for candidate in ('application', 'company', 'contact', 'invitation',
                          'opportunity', 'bill', 'program', 'project',
                          'tracked_opportunity'):
            target = getattr(note, candidate, None)
            if target is not None:
                return target
        return note

    def _guess_product_code(self, source, note) -> str:
        """Derive the source_product slug from settings, falling back to the
        note model's app label.

        ``KEEL_PRODUCT_CODE`` is the canonical machine identifier shipped
        in keel >= 0.41.0 and is what each product sets in its own
        settings.py. Using it here keeps the retry's POST payload
        consistent with the original dispatch's payload, so Beacon's
        idempotency key (contact_slug, source_url) matches.
        """
        from django.conf import settings
        product = (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower()
        if product:
            return product
        # Fall back to app label of the note model.
        return type(note)._meta.app_label.lower()


def _short(url: str, limit: int = 60) -> str:
    if not url or len(url) <= limit:
        return url
    return url[: limit - 1] + '…'
