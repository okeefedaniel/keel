"""Public service-layer API for keel.activity.

The two main entry points are ``record_activity()`` (Track B — explicit calls from
product service code) and ``build_deep_link()`` (helper for converting a target's
``get_absolute_url()`` to an absolute URL using ``KEEL_PRODUCT_BASE_URL``).

The module-level ``_skip_promotion`` ContextVar is the guard that prevents
``record_activity()`` from double-creating activity rows: when ``record_activity()`` is
running, it writes both AuditLog and Activity in one atomic transaction, and the
post_save signal on AuditLog (Track A registry promotion) sees the guard is True and
skips. ContextVar (not threading.local) so async-safe — the guard travels with the
async context.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

logger = logging.getLogger(__name__)

# True iff the current execution context is inside a record_activity() call.
# Track A (registry promotion via post_save on AuditLog) checks this and skips
# when True to avoid double-creating an Activity row that record_activity() is
# already creating in the same transaction.
_skip_promotion: ContextVar[bool] = ContextVar('keel_activity_skip_promotion', default=False)


@contextmanager
def skip_promotion_guard():
    """Context manager form of the _skip_promotion ContextVar.

    Used internally by ``record_activity()``. Exposed for product code that wants to
    suppress promotion for a block of saves (rare; usually a sign of a different bug).
    """
    token = _skip_promotion.set(True)
    try:
        yield
    finally:
        _skip_promotion.reset(token)


def is_promotion_skipped() -> bool:
    """Public read accessor for signal handlers."""
    return _skip_promotion.get()


def build_deep_link(target) -> str:
    """Resolve ``target.get_absolute_url()`` and prefix with ``KEEL_PRODUCT_BASE_URL``.

    Returns an empty string on any failure (target is None, no get_absolute_url method,
    NoReverseMatch, base URL not configured). Activity rows tolerate empty deep_link;
    UI shows a non-clickable label.
    """
    if target is None:
        return ''
    try:
        relative = target.get_absolute_url()
    except Exception:
        logger.debug('build_deep_link: target.get_absolute_url() failed for %r', target,
                     exc_info=True)
        return ''
    if not relative:
        return ''
    base = getattr(settings, 'KEEL_PRODUCT_BASE_URL', '').rstrip('/')
    if base:
        return f'{base}{relative}'
    # No base URL configured — return the relative path. Helm aggregator will refuse
    # to consume rows with relative deep_links, which is the right failure mode
    # (forces base URL configuration before suite-mode aggregation lights up).
    return relative


def record_activity(
    actor,
    verb: str,
    target,
    *,
    action=None,
    visibility: str = 'collaborators',
    metadata: Optional[dict] = None,
    audit_action: str = 'create',
    deep_link: Optional[str] = None,
    source_label: Optional[str] = None,
):
    """Track B — explicit activity emission from product service code.

    Writes both an AuditLog row AND an Activity row in one atomic transaction. The
    ``_skip_promotion`` guard prevents Track A from also firing for the same audit row.

    Args:
        actor: User instance or None (for system events).
        verb: dotted snake_case from VERB_CATALOG (e.g. ``'signing.signed'``).
        target: the primary record this activity is about. May be None for system
            events (``'system.aggregator_imported'`` etc.).
        action: optional secondary GFK target — the specific row that was created/changed
            (e.g. for ``'collab.added'``: target=Project, action=Collaborator row).
        visibility: one of VISIBILITY_CHOICES. Default 'collaborators'.
        metadata: free-form dict for structured context. from/to status, signer email,
            zone, role, etc. Goes into both the AuditLog ``metadata`` field AND the
            Activity ``metadata`` field (the audit ``changes`` field stays empty —
            ``changes`` retains its diff semantics for auto-signal saves).
        audit_action: the AuditLog.Action value to use. Defaults to 'create'. Service
            code that performs a status transition should pass 'status_change' so the
            audit row reflects the semantic, not the create/update mechanic.
        deep_link: optional explicit URL. If unset, computed from ``target.get_absolute_url()``.
        source_label: optional explicit human-readable summary. If unset, defaults to
            ``f'{actor} {verb}'``.

    Returns the created Activity instance.

    Raises:
        ImproperlyConfigured (via lazy apps.get_model) if KEEL_ACTIVITY_MODEL or
        KEEL_AUDIT_LOG_MODEL are not configured.
    """
    Activity = apps.get_model(settings.KEEL_ACTIVITY_MODEL)
    AuditLog = apps.get_model(settings.KEEL_AUDIT_LOG_MODEL)

    metadata = metadata or {}
    deep_link = deep_link if deep_link is not None else build_deep_link(target)
    source_label = source_label or (f'{actor} {verb}' if actor else f'system {verb}')

    target_ct = ContentType.objects.get_for_model(target.__class__) if target else None
    target_id = target.pk if target else None

    with skip_promotion_guard():
        with transaction.atomic():
            # AuditLog gets the metadata in the new ``metadata`` field (added to
            # AbstractAuditLog as part of Phase 1A). ``changes`` stays empty for
            # explicit record_activity() calls — it carries diff semantics that the
            # audit-signal pathway populates for plain saves, and we don't want to
            # pollute that channel with free-form context.
            audit_kwargs = dict(
                user=actor,
                action=audit_action,
                entity_type=_entity_type_for_target(target),
                entity_id=str(target_id) if target_id is not None else '',
                description=source_label,
                changes={},
                ip_address=None,  # record_activity() may run outside a request context
            )
            # AbstractAuditLog now carries metadata + deep_link_snapshot fields
            # (added in Phase 1A keel.core change). Be defensive in case the field
            # is missing on a not-yet-migrated product.
            if hasattr(AuditLog, 'metadata') or 'metadata' in [f.name for f in AuditLog._meta.fields]:
                audit_kwargs['metadata'] = metadata
            if 'deep_link_snapshot' in [f.name for f in AuditLog._meta.fields]:
                audit_kwargs['deep_link_snapshot'] = deep_link

            audit = AuditLog.objects.create(**audit_kwargs)

            activity = Activity.objects.create(
                actor=actor,
                verb=verb,
                target_ct=target_ct,
                target_id=target_id,
                visibility=visibility,
                source_product=settings.KEEL_PRODUCT_CODE,
                deep_link=deep_link,
                source_label=source_label,
                audit_ref=audit,
                metadata=metadata,
            )
            if action is not None:
                activity.action_ct = ContentType.objects.get_for_model(action.__class__)
                activity.action_id = action.pk
                activity.save(update_fields=['action_ct', 'action_id'])

    return activity


VALID_SYSTEM_EVENT_STATUSES = ('ok', 'warn', 'failed', 'errored')


def record_system_event(
    verb: str,
    summary: str,
    *,
    metadata: Optional[dict] = None,
    target=None,
    visibility: str = 'staff',
    status: str = 'ok',
):
    """Record a material system event with a narrative summary.

    Under Approach D (see ``~/.claude/plans/audit-activity-notifications-rethink.md``),
    system events flow into ``Activity`` ONLY — NOT into ``AuditLog``. AuditLog is the
    schema-enforced "what users did" surface (``user NOT NULL``); system events have
    no user and therefore no home there. The Activity stream is the canonical
    "what happened" log and is the seam that ``dispatch_activity_notifications``
    fans out from for cron failures.

    Routine ``status='ok'`` rows are pull-only — they appear on the cross-product
    ``/ops/`` console but the registered NotificationType for routine verbs uses
    ``channels=[]`` so no inbox push. ``status in ('failed', 'errored')`` rows
    use the normal notification pipeline and reach product ``system_admin``s.

    Args:
        verb: dotted snake_case identifier (e.g. ``'grants_gov.polled'``,
            ``'salesforce.synced'``, ``'foia.cache_refreshed'``). Reuse a registered
            verb if one already covers this event; the verb is the join key for
            ``/ops/`` filtering and notification routing.
        summary: human-readable one-line description. Should include a quantitative
            count where possible — "Grants.gov poll: +2 new, ~3 updated, 1 closed,
            312 unchanged" beats "poll complete". Goes into the Activity row's
            ``source_label`` and is also stored in ``metadata['summary']``.
        metadata: free-form structured detail (new_ids, duration_ms, source URL,
            agency code, etc). Merged with the ``summary`` / ``status`` keys this
            helper sets — caller MUST NOT use ``summary`` or ``status`` keys in
            its own metadata dict.
        target: optional GenericForeignKey target. Most cron summaries leave this
            None (the poll isn't "about" a specific record). Pass a target when
            the event materially relates to one record — e.g. a webhook retry
            attached to its source packet.
        visibility: AbstractActivity.VISIBILITY_CHOICES. Defaults to ``'staff'`` —
            system events are operational, not collaborator-facing. Cross-product
            crossings (Yeoman → Beacon contact creation, Bounty → Harbor grant
            push) may pass ``'agency'`` so per-agency staff see them too.
        status: one of ``'ok' | 'warn' | 'failed' | 'errored'``. Drives row color
            on ``/ops/`` Row 2 and gates the failure-notification fan-out.

    Returns the created Activity instance, or None if Activity isn't configured
    (KEEL_ACTIVITY_MODEL unset — fail-soft for products mid-rollout).

    Raises:
        ValueError if ``status`` is not a recognized value (catches typos at
        write time rather than producing un-categorizable rows).
    """
    if status not in VALID_SYSTEM_EVENT_STATUSES:
        raise ValueError(
            f'record_system_event: status must be one of '
            f'{VALID_SYSTEM_EVENT_STATUSES!r}, got {status!r}'
        )

    activity_model_path = getattr(settings, 'KEEL_ACTIVITY_MODEL', '')
    if not activity_model_path:
        # No Activity configured on this product — fail-soft, log, return None.
        # This lets a not-yet-migrated product import this module without
        # crashing; the cron's run-log still gets the CommandRun row from
        # @scheduled_job, which is the minimum viable observability.
        logger.warning(
            'record_system_event(%r): KEEL_ACTIVITY_MODEL unset, dropping event. '
            'Configure it to capture system-event narratives.',
            verb,
        )
        return None

    try:
        Activity = apps.get_model(activity_model_path)
    except LookupError:
        logger.exception(
            'record_system_event(%r): KEEL_ACTIVITY_MODEL=%s did not resolve',
            verb, activity_model_path,
        )
        return None

    # Runtime guard: a request-context call to record_system_event is almost
    # certainly a mistake — the caller probably wants record_activity() with
    # actor=request.user. Warn but don't block (some legitimate edge cases:
    # a user-triggered batch import that emits a per-batch summary).
    actor = None
    user, _ip = _maybe_get_audit_context()
    if user is not None and getattr(user, 'is_authenticated', False):
        logger.warning(
            'record_system_event(%r) called inside a request context with '
            'authenticated user=%r. Did you mean record_activity(actor=user, ...)? '
            'Continuing with actor=None per the system-event contract.',
            verb, user,
        )

    merged_metadata = {'summary': summary, 'status': status, **(metadata or {})}

    target_ct = ContentType.objects.get_for_model(target.__class__) if target else None
    target_id = target.pk if target else None

    with skip_promotion_guard():
        with transaction.atomic():
            activity = Activity.objects.create(
                actor=actor,
                verb=verb,
                target_ct=target_ct,
                target_id=str(target_id) if target_id is not None else None,
                visibility=visibility,
                source_product=getattr(settings, 'KEEL_PRODUCT_CODE', ''),
                deep_link=build_deep_link(target),
                source_label=summary,
                audit_ref=None,
                metadata=merged_metadata,
            )

    return activity


def _maybe_get_audit_context():
    """Get the current audit context without importing at module level.

    keel.activity is sometimes installed before keel.core's audit_signals
    is fully importable (test bootstrap order). Lazy-import inside the
    function so module load order doesn't matter.
    """
    try:
        from keel.core.audit_signals import get_audit_context
        return get_audit_context()
    except Exception:
        return (None, None)


def _entity_type_for_target(target) -> str:
    """Best-effort entity_type string for the AuditLog row. Falls back to the model's
    verbose_name if no audit registry entry exists for it."""
    if target is None:
        return ''
    # Prefer the audit_signals registry display name if registered (matches Track A
    # entity_type semantics).
    from keel.core import audit_signals
    model_label = f'{target._meta.app_label}.{target.__class__.__name__}'
    entry = audit_signals.get_audited_models().get(model_label)
    if entry:
        return entry.display_name
    # Fall back to the model's verbose_name (Title-cased).
    return str(target._meta.verbose_name).title()
