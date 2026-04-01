"""
Microsoft Graph / Outlook Calendar provider.

Stub implementation. When credentials are available, implement using
msal + Microsoft Graph API v1.0.

Since all DockLabs products already use Microsoft Entra ID SSO via
django-allauth, the OAuth2 plumbing is largely in place. Real
implementation would:
    1. Use msal.ConfidentialClientApplication to acquire token
    2. POST https://graph.microsoft.com/v1.0/me/events to create
    3. PATCH .../events/{id} to update, DELETE to cancel
    4. POST /me/calendar/getSchedule for availability

Settings:
    KEEL_CALENDAR_MICROSOFT_TENANT_ID
    KEEL_CALENDAR_MICROSOFT_CLIENT_ID
    KEEL_CALENDAR_MICROSOFT_CLIENT_SECRET
"""
import logging
import uuid
from types import SimpleNamespace

logger = logging.getLogger(__name__)


def create_event(user, title, start, end, location, description, metadata):
    """Create a calendar event. Returns (external_id, error)."""
    logger.info(
        "[CALENDAR:MICROSOFT] Would create event '%s' for %s (%s - %s)",
        title, user, start, end,
    )
    return (f"microsoft-{uuid.uuid4().hex[:12]}", "")


def update_event(external_id, user, **fields):
    """Update an existing event. Returns (success, error)."""
    logger.info(
        "[CALENDAR:MICROSOFT] Would update event %s: %s",
        external_id, list(fields.keys()),
    )
    return (True, "")


def delete_event(external_id, user):
    """Delete/cancel an event. Returns (success, error)."""
    logger.info("[CALENDAR:MICROSOFT] Would delete event %s", external_id)
    return (True, "")


def check_availability(user, start, end):
    """Check if user is available. Returns (available, conflicts, error)."""
    logger.info(
        "[CALENDAR:MICROSOFT] Would check availability for %s (%s - %s)",
        user, start, end,
    )
    return (True, [], "")


microsoft_provider = SimpleNamespace(
    create_event=create_event,
    update_event=update_event,
    delete_event=delete_event,
    check_availability=check_availability,
)
