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
