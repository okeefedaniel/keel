"""Bulk / automated ChangeRequest ingestion.

The single entry point for AUTOMATED, high-volume creation of
ChangeRequests — nightly test failures and security-audit findings.
Creating N rows through here dispatches exactly ONE aggregated admin
notification, not N, via :func:`keel.notifications.digest.notify_batch`.

Human, low-volume submissions deliberately do NOT come through here:
the in-product feedback widget (``views.api_ingest`` /
``views.submit_request``) calls ``notify`` per item so the admin sees each
one individually. The flood this module exists to prevent is the nightly
suite: on a bad night it emitted ~100 near-identical "New Bug Report"
emails in a single minute because each failure was POSTed one at a time to
``api_ingest``. See ``keel/scripts/nightly.sh`` Phase 3 and the digest
post-mortem note in ``keel/CLAUDE.md``.
"""
import logging

from django.contrib.auth import get_user_model

from keel.notifications.digest import notify_batch

from .models import Category, ChangeRequest, Priority, Status

logger = logging.getLogger(__name__)

# Statuses that count as "already being handled" for dedupe purposes. A new
# automated report whose title matches an OPEN request is dropped rather than
# piling a duplicate onto the dashboard every run.
OPEN_STATUSES = (Status.PENDING, Status.APPROVED, Status.IMPLEMENTING)

# Default digest notification type. Purpose-built (see
# keel.notifications.product_types.register_keel_platform_types) with
# in_app + email channels and admin / system_admin roles — no sms/boswell
# fan-out, unlike ``change_request_submitted``.
DEFAULT_DIGEST_EVENT = 'test_suite_failure'


def _open_duplicate_exists(title):
    """True if an OPEN ChangeRequest already covers this title.

    Mirrors the historical dedupe in ``keel.testing.__main__`` — matches on
    the first 80 chars so counts/timings appended to a title don't defeat it.
    """
    return ChangeRequest.objects.filter(
        title__icontains=title[:80],
        status__in=OPEN_STATUSES,
    ).exists()


def _default_admin_recipients():
    """Active superusers — the recipients of automated dashboard digests.

    Matches ``views._notify_admins_api`` so the digest reaches the same
    people the per-item path used to.
    """
    User = get_user_model()
    return list(User.objects.filter(is_superuser=True, is_active=True))


def bulk_ingest_change_requests(
    items,
    *,
    recipients=None,
    notify_admins=True,
    event=DEFAULT_DIGEST_EVENT,
    summary_title=None,
    summary_prefix=None,
    link='/keel/requests/',
    dedupe=True,
    default_submitted_by_name='Automated',
    default_submitted_by_email='',
):
    """Create many ChangeRequests and send ONE aggregated admin notification.

    Args:
        items: Iterable of dicts. Recognized keys: ``title`` (required),
            ``description`` (required), ``product``, ``category``,
            ``priority``, ``page_url``, ``submitted_by_name``,
            ``submitted_by_email``. Rows missing title/description are skipped.
        recipients: Explicit notification recipients. If None and
            ``notify_admins`` is True, active superusers are used.
        notify_admins: When False (and no explicit recipients), no notification
            is sent — rows are still created. Use for a silent bulk import.
        event: Notification registry key for the digest.
        summary_title / summary_prefix: Digest title / body-prefix. May contain
            ``{count}``.
        link: Digest detail link (e.g. a filtered dashboard view).
        dedupe: When True, skip items whose title matches an OPEN request.
        default_submitted_by_name / default_submitted_by_email: Applied to
            items that don't carry their own.

    Returns:
        dict: ``{'created': int, 'skipped': int, 'ids': [str, ...]}`` where
        ``skipped`` counts both dedupe hits and malformed items.
    """
    created = []
    skipped = 0

    resolved_recipients = recipients
    if resolved_recipients is None and notify_admins:
        resolved_recipients = _default_admin_recipients()
    elif not notify_admins:
        resolved_recipients = []

    with notify_batch(
        event=event,
        recipients=resolved_recipients,
        summary_title=summary_title,
        summary_prefix=summary_prefix,
        link=link,
    ) as batch:
        for item in items:
            title = (item.get('title') or '').strip()
            description = (item.get('description') or '').strip()
            if not title or not description:
                skipped += 1
                continue

            if dedupe and _open_duplicate_exists(title):
                skipped += 1
                continue

            cr = ChangeRequest.objects.create(
                submitted_by=None,
                submitted_by_name=(
                    item.get('submitted_by_name') or default_submitted_by_name
                ),
                submitted_by_email=(
                    item.get('submitted_by_email') or default_submitted_by_email
                ),
                product=(item.get('product') or 'unknown').strip().lower(),
                title=title[:255],
                description=description,
                category=(item.get('category') or Category.BUG),
                priority=(item.get('priority') or Priority.MEDIUM),
                page_url=(item.get('page_url') or '').strip(),
            )
            created.append(cr)
            batch.add(
                title=cr.title,
                detail=cr.product,
                link=f'/keel/requests/{cr.id}/',
            )

    return {
        'created': len(created),
        'skipped': skipped,
        'ids': [str(c.id) for c in created],
    }
