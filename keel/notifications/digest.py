"""Notification digest / batching.

Collapse many same-run notifications into ONE. A bulk or automated loop
(nightly test-failure ingestion, security-audit ingestion, a bulk import)
that calls :func:`keel.notifications.dispatch.notify` per item fans out into
one email per item and buries the recipient — the nightly suite once put 98
near-identical "New Bug Report" emails in Dan's inbox in a single minute.

:func:`notify_batch` is a context manager that collects items inside the
``with`` block and, on clean exit, sends a SINGLE summary notification (count
+ a truncated list) through the normal :func:`notify` machinery, so channel
resolution, per-recipient preferences, and delivery logging all still apply.

This is for BULK / AUTOMATED paths only. Low-volume human actions (a feedback
widget submission, a single approval) should keep calling :func:`notify`
directly so the recipient sees each one individually.

Example::

    with notify_batch(
        event='test_suite_failure',
        recipients=admins,
        summary_title='Nightly tests: {count} new failure(s)',
        link='/keel/requests/',
    ) as batch:
        for failure in failures:
            cr = ChangeRequest.objects.create(...)
            batch.add(title=cr.title, detail=cr.product, link=f'/keel/requests/{cr.id}/')
    # -> exactly one notification, regardless of how many items were added.
"""
import logging
from contextlib import contextmanager

from .dispatch import notify

logger = logging.getLogger(__name__)

# How many items to list in the digest body before truncating with a
# "…and N more" line. Keeps a 300-failure night from producing an
# unreadable wall of text while still being honest about the total.
DEFAULT_ITEM_LIMIT = 50


class NotificationBatch:
    """Accumulator handed to the ``with notify_batch(...) as batch`` block."""

    __slots__ = ('items',)

    def __init__(self):
        self.items = []

    def add(self, title, detail='', link=''):
        """Record one item for the digest.

        Args:
            title: Short one-line description of the item.
            detail: Optional extra context (e.g. product name) shown in parens.
            link: Optional per-item deep link (unused in the summary body today,
                captured for future per-item rendering).
        """
        self.items.append({'title': title, 'detail': detail, 'link': link})

    def __len__(self):
        return len(self.items)


def _render_summary(items, item_limit):
    """Render the collected items as a plain-text bullet list, truncated."""
    lines = []
    for item in items[:item_limit]:
        title = item.get('title', '').strip() or '(untitled)'
        detail = (item.get('detail') or '').strip()
        lines.append(f'- {title}' + (f' ({detail})' if detail else ''))
    remaining = len(items) - item_limit
    if remaining > 0:
        lines.append(f'- …and {remaining} more (see the dashboard for the full list).')
    return '\n'.join(lines)


@contextmanager
def notify_batch(event, recipients=None, summary_title=None,
                 summary_prefix=None, link='', priority=None,
                 item_limit=DEFAULT_ITEM_LIMIT, channels=None,
                 force=False, context=None):
    """Collect notify() items and dispatch ONE aggregated notification on exit.

    Args:
        event: Registry key for the aggregated notification (e.g.
            ``'test_suite_failure'``). Determines default channels/roles/priority.
        recipients: Explicit recipient list. If None, the event's role-based
            resolution is used (same as :func:`notify`).
        summary_title: Title for the digest. May contain ``{count}`` which is
            formatted with the number of collected items. If None, a default
            (``"N new <event>"``) is used.
        summary_prefix: First line of the body before the item list. May contain
            ``{count}``. If None, a default is used.
        link: Detail link for the digest (e.g. a filtered dashboard view).
        priority: Priority override; falls back to the event default.
        item_limit: Max items listed in the body before truncation.
        channels: Channel override; falls back to the event defaults.
        force: Passed through to :func:`notify`.
        context: Extra context dict passed to :func:`notify`.

    Yields:
        A :class:`NotificationBatch` to ``.add()`` items to.

    Notes:
        - An EMPTY batch sends nothing (never dispatch a "0 items" digest).
        - If the ``with`` body raises, the exception propagates and NO digest
          is sent — the caller decides whether to retry.
        - A failure inside the final :func:`notify` is caught and logged so a
          notification hiccup never breaks the caller's bulk work (the rows
          are already committed by then).
    """
    batch = NotificationBatch()
    yield batch

    count = len(batch)
    if count == 0:
        return  # Nothing collected — never send an empty digest.

    def _fmt(template, default):
        if template is None:
            return default
        try:
            return template.format(count=count)
        except (KeyError, IndexError, ValueError):
            return template

    title = _fmt(summary_title, f'{count} new {event.replace("_", " ")}')
    prefix = _fmt(summary_prefix, f'{count} item(s) reported this run:')
    body = prefix + '\n\n' + _render_summary(batch.items, item_limit)

    try:
        notify(
            event=event,
            recipients=recipients,
            title=title,
            message=body,
            link=link,
            priority=priority,
            channels=channels,
            force=force,
            context=context or {},
        )
    except Exception:
        logger.exception(
            'notify_batch: failed to dispatch digest for event %r (%d items)',
            event, count,
        )
