"""Signal wiring for keel.activity.

Two handlers:

1. ``on_audit_saved`` — Track A. Fires on every AuditLog row creation. Looks up a
   matching promotion rule via ``PromotionRegistry.lookup(entity_type, action)`` and,
   if found, creates an Activity row. Skipped when ``_skip_promotion`` ContextVar is
   True (set by ``record_activity()`` to prevent double-creation in Track B paths).

2. ``on_activity_saved`` — Notification fan-out. Fires on every Activity row creation
   and dispatches notifications via ``dispatch.dispatch_activity_notifications()``.

Both handlers swallow exceptions (logging them) rather than re-raising — promotion and
notification failures must never block the originating model save. The audit row IS
the durable record; activity is the user-visible projection that can fail and recover.
"""
from __future__ import annotations

import logging

from django.apps import apps
from django.conf import settings
from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


def connect_signals() -> None:
    """Connect post_save signals on the concrete AuditLog and Activity models.

    Called from ``ActivityConfig.ready()``. Uses ``apps.get_model()`` to resolve the
    swappable model targets at signal-connection time (after Django's app registry
    has loaded). Idempotent via ``dispatch_uid``.
    """
    audit_model_path = settings.KEEL_AUDIT_LOG_MODEL
    activity_model_path = settings.KEEL_ACTIVITY_MODEL

    try:
        AuditLog = apps.get_model(audit_model_path)
    except LookupError:
        logger.error(
            'KEEL_AUDIT_LOG_MODEL=%s could not be resolved. keel.activity signals not connected.',
            audit_model_path,
        )
        return

    try:
        Activity = apps.get_model(activity_model_path)
    except LookupError:
        logger.error(
            'KEEL_ACTIVITY_MODEL=%s could not be resolved. keel.activity signals not connected.',
            activity_model_path,
        )
        return

    post_save.connect(
        on_audit_saved, sender=AuditLog, weak=False,
        dispatch_uid='keel_activity_audit_promote',
    )
    post_save.connect(
        on_activity_saved, sender=Activity, weak=False,
        dispatch_uid='keel_activity_dispatch',
    )


def on_audit_saved(sender, instance, created, **kwargs):
    """Track A — promote audit rows to activity rows via the registry."""
    if not created:
        # AuditLog is immutable; updates raise. Skip defensively in case a non-immutable
        # subclass slips through.
        return

    from .services import is_promotion_skipped
    if is_promotion_skipped():
        # record_activity() is creating both rows; skip to prevent double-creation.
        return

    from .registry import PromotionRegistry
    rule = PromotionRegistry.lookup(instance.entity_type, instance.action)
    if rule is None:
        # No promotion rule for this audit row — common and expected. Audit captures
        # everything; activity is the curated subset.
        return

    try:
        activity_kwargs = rule.build_activity_kwargs(instance)
    except Exception:
        logger.exception(
            'Activity promotion rule failed for audit pk=%s entity_type=%r action=%r',
            instance.pk, instance.entity_type, instance.action,
        )
        return

    if activity_kwargs is None:
        # Rule chose to skip this row (e.g. target was deleted before promotion ran).
        return

    Activity = apps.get_model(settings.KEEL_ACTIVITY_MODEL)
    try:
        Activity.objects.create(audit_ref=instance, **activity_kwargs)
    except Exception:
        logger.exception(
            'Activity row creation failed for audit pk=%s verb=%r',
            instance.pk, rule.verb,
        )


def on_activity_saved(sender, instance, created, **kwargs):
    """Notification fan-out — every new Activity triggers dispatch."""
    if not created:
        return
    from .dispatch import dispatch_activity_notifications
    try:
        dispatch_activity_notifications(instance)
    except Exception:
        logger.exception(
            'Notification dispatch failed for activity pk=%s verb=%r',
            instance.pk, instance.verb,
        )
