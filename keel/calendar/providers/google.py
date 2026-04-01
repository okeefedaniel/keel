"""
Google Calendar provider.

Stub implementation. When credentials are available, implement using
google-api-python-client with OAuth2 service account or user delegation.

Settings:
    KEEL_CALENDAR_GOOGLE_CREDENTIALS_JSON — path to service account JSON
    KEEL_CALENDAR_GOOGLE_SCOPES — defaults to ['https://www.googleapis.com/auth/calendar']
"""
import logging
import uuid
from types import SimpleNamespace

logger = logging.getLogger(__name__)


def create_event(user, title, start, end, location, description, metadata):
    """Create a calendar event. Returns (external_id, error)."""
    logger.info(
        "[CALENDAR:GOOGLE] Would create event '%s' for %s (%s - %s)",
        title, user, start, end,
    )
    return (f"google-{uuid.uuid4().hex[:12]}", "")


def update_event(external_id, user, **fields):
    """Update an existing event. Returns (success, error)."""
    logger.info(
        "[CALENDAR:GOOGLE] Would update event %s: %s",
        external_id, list(fields.keys()),
    )
    return (True, "")


def delete_event(external_id, user):
    """Delete/cancel an event. Returns (success, error)."""
    logger.info("[CALENDAR:GOOGLE] Would delete event %s", external_id)
    return (True, "")


def check_availability(user, start, end):
    """Check if user is available. Returns (available, conflicts, error)."""
    logger.info(
        "[CALENDAR:GOOGLE] Would check availability for %s (%s - %s)",
        user, start, end,
    )
    return (True, [], "")


google_provider = SimpleNamespace(
    create_event=create_event,
    update_event=update_event,
    delete_event=delete_event,
    check_availability=check_availability,
)
