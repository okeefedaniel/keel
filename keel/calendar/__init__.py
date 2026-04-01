"""
keel.calendar — Shared calendar sync module for DockLabs products.

Provides a provider-agnostic interface for pushing events to external
calendars (Google Calendar, Microsoft Outlook) and generating iCal files.

Quick start:

    # In your AppConfig.ready():
    from keel.calendar import register, CalendarEventType

    register(CalendarEventType(
        key='invitation_scheduled',
        label='Invitation Scheduled',
        default_duration_minutes=60,
    ))

    # In your views/services:
    from keel.calendar import push_event

    result = push_event(
        event_type='invitation_scheduled',
        user=request.user,
        title=invitation.event_name,
        start=start_dt,
        end=end_dt,
        location=invitation.venue_name,
        content_object=invitation,
    )

Settings:
    KEEL_CALENDAR_PROVIDER — 'google' or 'microsoft' (default: None)
    KEEL_CALENDAR_EVENT_MODEL — dotted model path, e.g. 'core.CalendarEvent'
    KEEL_CALENDAR_SYNC_LOG_MODEL — dotted model path (optional)
"""
from .registry import CalendarEventType, register, get_type, get_all_types
from .service import push_event, update_event, cancel_event, check_availability
from .ical import generate_ical, generate_single_ical

__all__ = [
    'CalendarEventType',
    'register',
    'get_type',
    'get_all_types',
    'push_event',
    'update_event',
    'cancel_event',
    'check_availability',
    'generate_ical',
    'generate_single_ical',
]
