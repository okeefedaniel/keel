"""Auto-register every verb in VERB_CATALOG as a NotificationType.

The activity dispatch path emits notifications keyed as ``activity.<verb.code>``
(see ``keel.activity.dispatch._fan_out``). Without a corresponding
NotificationType registered, those notifications:

  - never appear on /notifications/preferences/, so users can't mute them;
  - bypass per-user preference filtering, so muting "all activity" doesn't work;
  - render with the verb code as the label instead of a human-readable string.

This module bridges the gap. Called once from ``ActivityConfig.ready()``:

  1. Iterate VERB_CATALOG.
  2. For each Verb, register a NotificationType with key=``activity.<code>``.
  3. Skip if the key is already registered (a product wired a richer override).
  4. Auto-categorize by verb namespace prefix ("workflow.transitioned" → "Workflow",
     "signing.completed" → "Signing", etc.).

Internal verbs (default_visibility == 'staff') are registered with internal=True so
they appear on the admin-only / debug enumeration but NOT on the user-facing
preferences page — consistent with the existing internal flag for system
notifications elsewhere in keel.

Default channels: in_app + email when default_notify=True; in_app only when False.
Users can still toggle either channel on/off from the preferences page.
"""
from __future__ import annotations

import logging

from keel.activity.verbs import VERB_CATALOG, Verb

logger = logging.getLogger(__name__)


# Human-readable category labels for the preferences UI, keyed by verb namespace.
# Falls back to the namespace title-cased when not in this map.
NAMESPACE_LABELS = {
    'lifecycle': 'Record lifecycle',
    'collab': 'Collaborators',
    'diligence': 'Notes & attachments',
    'interaction': 'Interactions',
    'workflow': 'Workflow',
    'signing': 'Signing',
    'cross': 'Cross-product',
    'foia': 'FOIA',
    'comms': 'Communications',
    'compliance': 'Compliance',
    'system': 'System events',
}


def _category_for(verb: Verb) -> str:
    namespace = verb.code.split('.', 1)[0]
    return NAMESPACE_LABELS.get(namespace, namespace.title())


def _description_for(verb: Verb) -> str:
    """Use the verb's own description, or synthesize a short one if missing."""
    if verb.description:
        return verb.description
    # Synthesize: "<Label> notifications for records you follow or collaborate on."
    return (
        f'{verb.label} notifications for records you follow or collaborate on.'
    )


def register_verb_notification_types() -> int:
    """Register a NotificationType for every verb in VERB_CATALOG.

    Returns the count of types registered. Idempotent: re-runs are safe (the
    underlying registry overwrites with a warning log; we skip if already present
    to keep the warning quiet on every startup).

    Returns 0 if keel.notifications isn't installed (legacy fork) — we silently
    no-op rather than raising, so a product without notifications still boots.
    """
    try:
        from keel.notifications.registry import (
            NotificationType, get_type, register,
        )
    except ImportError:
        logger.debug('keel.notifications not installed; skipping verb auto-registration')
        return 0

    registered = 0
    for verb in VERB_CATALOG.values():
        key = f'activity.{verb.code}'
        if get_type(key) is not None:
            # A product or earlier import already registered this — leave it alone.
            continue

        is_staff_only = verb.default_visibility == 'staff'
        default_channels = (
            ['in_app', 'email'] if verb.default_notify else ['in_app']
        )
        register(NotificationType(
            key=key,
            label=verb.label,
            description=_description_for(verb),
            category=_category_for(verb),
            default_channels=default_channels,
            default_roles=['all'],
            priority='medium',
            allow_mute=True,
            internal=is_staff_only,
        ))
        registered += 1

    if registered:
        logger.info(
            'keel.activity: auto-registered %d verb-keyed NotificationTypes',
            registered,
        )
    return registered
