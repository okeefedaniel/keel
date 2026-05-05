"""Notification fan-out from activity rows.

Subscriber resolution priority:

    1. Verb-specific recipient_resolver (registered via keel.notifications.NotificationType)
       wins. Used by ``signing.next_signer_active`` to route to the new active signer
       instead of collaborators-of-target.

    2. Standard collab + watcher + role resolution otherwise.

Every candidate subscriber is checked against ``Activity.is_visible_to_user(user, activity)``
before a notification fires. This is the gate that prevents stub-tier rows from leaking
to external watchers in Beacon's zone-bridge scenario.

Dedup: per-product Notification has ``UniqueConstraint(['user', 'activity_ref'])`` (added
in Phase 1A keel.notifications change). Duplicate fan-out attempts no-op via the
constraint; ``notify()`` uses ``get_or_create`` semantics.
"""
from __future__ import annotations

import logging
from typing import Iterable, Set

from django.apps import apps
from django.conf import settings
from django.db.models import Q

logger = logging.getLogger(__name__)


def dispatch_activity_notifications(activity) -> None:
    """Fire notifications for every subscriber of this activity row.

    Called from the post_save signal on Activity (see ``signals.on_activity_saved``).
    Swallows exceptions caller-side — notification failures don't block the originating
    save. Per-channel delivery failures (email backend down, etc.) are tracked in
    NotificationLog by the underlying ``notify()`` dispatcher.
    """
    Activity = apps.get_model(settings.KEEL_ACTIVITY_MODEL)

    # Path 1: verb-specific recipient_resolver wins.
    recipient_resolver = _get_recipient_resolver(activity.verb)
    if recipient_resolver is not None:
        try:
            subscribers = set(recipient_resolver(activity))
        except Exception:
            logger.exception(
                'recipient_resolver for activity.%s raised; falling back to standard resolution',
                activity.verb,
            )
            subscribers = _standard_subscribers(activity)
    else:
        subscribers = _standard_subscribers(activity)

    if not subscribers:
        return

    # Visibility filter — never notify a user who can't see the row. Stub-tier rows
    # are always filtered here because the per-product is_visible_to_user implementation
    # checks zone access for stub visibility (Beacon's contract).
    visible_subscribers = []
    for user in subscribers:
        try:
            if Activity.is_visible_to_user(user, activity):
                visible_subscribers.append(user)
        except NotImplementedError:
            logger.error(
                'Activity.is_visible_to_user not implemented on %s; skipping all notifications',
                Activity.__name__,
            )
            return
        except Exception:
            logger.exception(
                'is_visible_to_user raised for user pk=%s activity pk=%s; skipping this user',
                getattr(user, 'pk', None), activity.pk,
            )

    if not visible_subscribers:
        return

    # Hand off to keel.notifications.notify(). Pass the activity so the notification row
    # gets activity_ref populated for dedup and so the notification can render with the
    # activity's deep_link / source_label.
    _fan_out(visible_subscribers, activity)


def _standard_subscribers(activity) -> Set:
    """Collab + watcher + role resolution. Empty set if the target has none."""
    subscribers: Set = set()
    subscribers.update(_resolve_collaborator_subscribers(activity))
    subscribers.update(_resolve_watcher_subscribers(activity))
    subscribers.update(_resolve_role_subscribers(activity))
    return subscribers


def _resolve_collaborator_subscribers(activity) -> Set:
    """Find collaborators on activity.target with the right notify_on_* flag.

    Defensive: if the target doesn't have a ``collaborators`` related manager (because it
    doesn't extend AbstractCollaborator), returns empty set.
    """
    target = activity.target
    if target is None:
        return set()
    if not hasattr(target, 'collaborators'):
        return set()

    # Map verb → notify_on_* flag on AbstractCollaborator. Verbs without a flag mapping
    # default to firing for all active collaborators.
    flag_field = {
        'diligence.note_posted': 'notify_on_notes',
        'workflow.transitioned': 'notify_on_status',
    }.get(activity.verb)

    qs = target.collaborators.filter(is_active=True, user__isnull=False)
    if flag_field:
        qs = qs.filter(**{flag_field: True})

    return {c.user for c in qs.select_related('user')}


def _resolve_watcher_subscribers(activity) -> Set:
    """Find Watcher rows matching this activity row.

    Per the eng plan, Watchers are product-local in v1 (cross-product Watchers deferred
    to Phase 2). The lookup uses the local ``KEEL_WATCHER_MODEL``.
    """
    try:
        Watcher = apps.get_model(settings.KEEL_WATCHER_MODEL)
    except LookupError:
        return set()

    target_ct_id = activity.target_ct_id
    target_id = activity.target_id

    candidates = Watcher.objects.filter(
        Q(target_ct_id__isnull=True) | Q(target_ct_id=target_ct_id),
        Q(target_id__isnull=True) | Q(target_id=target_id),
    ).select_related('user')

    return {w.user for w in candidates if w.matches(activity)}


def _resolve_role_subscribers(activity) -> Set:
    """Hook for role-based auto-subscriptions. Empty in v1.

    Future use: a system_admin role could auto-subscribe to ``signing.handoff_failed``
    and similar staff-visibility verbs. Today, products that want this register an
    explicit recipient_resolver on the verb's NotificationType.
    """
    return set()


def _get_recipient_resolver(verb: str):
    """Look up the verb's NotificationType.recipient_resolver, if any.

    Returns the callable or None. The notification key follows the convention
    ``activity.<verb>`` (e.g. ``activity.signing.next_signer_active``). Verbs that don't
    register a NotificationType return None and fall through to standard resolution.
    """
    try:
        from keel.notifications.registry import notification_registry
    except ImportError:
        return None

    notif_type = notification_registry.get(f'activity.{verb}')
    if notif_type is None:
        return None
    return getattr(notif_type, 'recipient_resolver', None)


def _fan_out(users: Iterable, activity) -> None:
    """Call keel.notifications.notify() for each user. Idempotent via UniqueConstraint."""
    try:
        from keel.notifications.dispatch import notify
    except ImportError:
        logger.error('keel.notifications not installed; cannot dispatch activity notifications')
        return

    notification_type = f'activity.{activity.verb}'
    for user in users:
        try:
            notify(
                user=user,
                notification_type=notification_type,
                # ``activity`` kwarg is read by the modified notify() to populate
                # Notification.activity_ref. Older notify() implementations that
                # don't accept the kwarg will TypeError; the keel.notifications.dispatch
                # change in Phase 1A adds the kwarg.
                activity=activity,
                link=activity.deep_link,
                label=activity.source_label,
            )
        except TypeError as e:
            # notify() doesn't yet accept `activity` kwarg (Phase 1A keel.notifications
            # change not landed yet). Fall back to no-activity-ref notification.
            logger.warning(
                'notify() does not accept activity kwarg yet (%s); falling back without activity_ref',
                e,
            )
            try:
                notify(
                    user=user,
                    notification_type=notification_type,
                    link=activity.deep_link,
                    label=activity.source_label,
                )
            except Exception:
                logger.exception(
                    'notify() fallback also failed for user pk=%s activity pk=%s',
                    user.pk, activity.pk,
                )
        except Exception:
            logger.exception(
                'notify() raised for user pk=%s activity pk=%s verb=%r',
                user.pk, activity.pk, activity.verb,
            )
