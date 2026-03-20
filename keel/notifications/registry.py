"""Notification type registry.

Products register their notification types at startup. The registry
provides a central catalog of all notification events, their default
channels, recipient roles, and templates.
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Global registry — populated by products during AppConfig.ready()
_registry: dict[str, 'NotificationType'] = {}


@dataclass
class NotificationType:
    """Definition of a notification event.

    Attributes:
        key: Unique identifier (e.g., 'application_submitted').
            Convention: '{entity}_{action}' using snake_case.
        label: Human-readable name for preferences UI.
        description: Longer description for preferences page.
        category: Grouping for the preferences UI (e.g., 'Applications',
            'FOIA', 'Grants'). Defaults to 'General'.
        default_channels: Channels enabled by default if user has no
            preference set. Options: 'in_app', 'email', 'sms'.
        default_roles: Roles that receive this notification by default.
            Use 'all' for all authenticated users.
            Products define their own role values.
        priority: Default priority level ('low', 'medium', 'high', 'urgent').
        email_template: Path to email template (HTML). A matching .txt
            template is auto-discovered for plain-text fallback.
        email_subject: Subject line template string. Can use {context} vars.
            If None, uses the notification title.
        recipient_resolver: Optional callable(event_context) -> list[User].
            When provided, overrides role-based resolution.
            Receives the full context dict passed to notify().
        agency_scoped: If True, role-based resolution filters by the
            agency associated with the context object.
        agency_field: Dot-path to extract agency from context for scoping.
            E.g., 'application.grant_program.agency' or 'award.agency'.
        allow_mute: Whether users can mute this notification type.
            Set False for critical system notifications.
    """
    key: str
    label: str
    description: str = ''
    category: str = 'General'
    default_channels: list[str] = field(default_factory=lambda: ['in_app', 'email'])
    default_roles: list[str] = field(default_factory=list)
    priority: str = 'medium'
    email_template: Optional[str] = None
    email_subject: Optional[str] = None
    recipient_resolver: Optional[Callable] = None
    agency_scoped: bool = False
    agency_field: str = ''
    allow_mute: bool = True


def register(notification_type: NotificationType):
    """Register a notification type in the global registry.

    Call this in your product's AppConfig.ready() or in a dedicated
    notifications.py module that's imported during ready().

    Duplicate keys log a warning and overwrite the previous entry.
    """
    if notification_type.key in _registry:
        logger.warning(
            'Notification type %r re-registered (overwriting)',
            notification_type.key,
        )
    _registry[notification_type.key] = notification_type


def get_type(key: str) -> Optional[NotificationType]:
    """Look up a registered notification type by key."""
    return _registry.get(key)


def get_all_types() -> dict[str, NotificationType]:
    """Return all registered notification types."""
    return dict(_registry)


def get_types_by_category() -> dict[str, list[NotificationType]]:
    """Return notification types grouped by category (for preferences UI)."""
    by_cat: dict[str, list[NotificationType]] = {}
    for nt in _registry.values():
        by_cat.setdefault(nt.category, []).append(nt)
    return by_cat


def clear_registry():
    """Clear all registered types. Used in testing."""
    _registry.clear()
