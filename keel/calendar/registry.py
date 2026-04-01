"""
Calendar event type registry.

Products register their calendar event types in AppConfig.ready(),
similar to keel.notifications.registry.

Usage:
    from keel.calendar import register, CalendarEventType

    register(CalendarEventType(
        key='invitation_scheduled',
        label='Invitation Scheduled',
        default_duration_minutes=60,
    ))
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_registry: dict[str, 'CalendarEventType'] = {}


@dataclass(frozen=True)
class CalendarEventType:
    """Defines a type of calendar event a product can push."""

    key: str
    label: str
    description: str = ''
    default_provider: Optional[str] = None  # None = use KEEL_CALENDAR_PROVIDER
    default_duration_minutes: int = 60
    include_location: bool = True
    include_description: bool = True
    title_template: Optional[str] = None  # e.g. '{event_name} - {org}'


def register(event_type: CalendarEventType) -> None:
    """Register a calendar event type. Warns on duplicate keys."""
    if event_type.key in _registry:
        logger.warning(
            "CalendarEventType '%s' is already registered; overwriting.",
            event_type.key,
        )
    _registry[event_type.key] = event_type


def get_type(key: str) -> Optional[CalendarEventType]:
    """Get a registered calendar event type by key."""
    return _registry.get(key)


def get_all_types() -> dict[str, CalendarEventType]:
    """Return all registered calendar event types."""
    return dict(_registry)


def clear_registry() -> None:
    """Clear all registered types. Useful for testing."""
    _registry.clear()
