"""
Calendar service — main dispatch layer for calendar operations.

Follows the same pattern as keel.notifications.dispatch:
    - Service functions as primary API
    - Provider resolution from settings
    - Optional model persistence via apps.get_model()
    - Sync logging when configured

Usage:
    from keel.calendar import push_event

    result = push_event(
        event_type='invitation_scheduled',
        user=request.user,
        title='CT Innovation Summit',
        start=datetime(2026, 5, 15, 9, 0),
        end=datetime(2026, 5, 15, 17, 0),
        location='Hartford Convention Center',
        content_object=invitation,
    )
    # result = {'success': True, 'external_id': '...', 'error': '', 'calendar_event_id': UUID}
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .providers import PROVIDERS
from .registry import get_type

logger = logging.getLogger(__name__)


def _get_provider(provider_key):
    """Look up a provider by key. Returns the provider namespace or None."""
    provider = PROVIDERS.get(provider_key)
    if not provider:
        logger.error("Unknown calendar provider: %s", provider_key)
    return provider


def _resolve_provider(provider=None, event_type_key=None):
    """Resolve which provider to use, checking args > event type > settings."""
    if provider:
        return provider

    if event_type_key:
        et = get_type(event_type_key)
        if et and et.default_provider:
            return et.default_provider

    return getattr(settings, 'KEEL_CALENDAR_PROVIDER', None)


def _save_event(user, event_type, title, description, location,
                start, end, all_day, provider_key, external_id, status,
                error, metadata, content_object, created_by):
    """Persist a CalendarEvent if the model is configured."""
    model_path = getattr(settings, 'KEEL_CALENDAR_EVENT_MODEL', None)
    if not model_path:
        return None

    try:
        from django.apps import apps
        EventModel = apps.get_model(model_path)

        ct = None
        obj_id = None
        if content_object is not None:
            ct = ContentType.objects.get_for_model(content_object)
            obj_id = content_object.pk

        event = EventModel.objects.create(
            user=user,
            event_type=event_type,
            title=title,
            description=description,
            location=location,
            start_time=start,
            end_time=end,
            all_day=all_day,
            provider=provider_key,
            external_id=external_id or '',
            status=status,
            sync_error=error or '',
            last_synced_at=timezone.now() if status == 'synced' else None,
            metadata=metadata or {},
            content_type=ct,
            object_id=obj_id,
            created_by=created_by,
        )
        return event.pk
    except Exception:
        logger.exception("Failed to save CalendarEvent")
        return None


def _log_sync(user, event_type, action, provider_key, success, error,
              request_payload=None, response_payload=None):
    """Log a sync attempt if the log model is configured."""
    model_path = getattr(settings, 'KEEL_CALENDAR_SYNC_LOG_MODEL', None)
    if not model_path:
        return

    try:
        from django.apps import apps
        LogModel = apps.get_model(model_path)
        LogModel.objects.create(
            user=user,
            event_type=event_type,
            action=action,
            provider=provider_key,
            success=success,
            error_message=error or '',
            request_payload=request_payload or {},
            response_payload=response_payload or {},
        )
    except Exception:
        logger.exception("Failed to save CalendarSyncLog")


def push_event(event_type, user, title, start, end=None,
               location='', description='', all_day=False,
               context=None, provider=None, content_object=None):
    """Push a new event to an external calendar.

    Args:
        event_type: Registry key (e.g. 'invitation_scheduled')
        user: The user whose calendar to push to
        title: Event title
        start: datetime for event start
        end: datetime for event end (defaults to start + default_duration_minutes)
        location: Physical or virtual location
        description: Event description/body
        all_day: Whether this is an all-day event
        context: Dict of provider-specific metadata
        provider: Override provider key ('google' or 'microsoft')
        content_object: Optional Django model instance to link via GenericFK

    Returns:
        dict with keys: success, external_id, error, calendar_event_id
    """
    provider_key = _resolve_provider(provider, event_type)
    if not provider_key:
        return {
            'success': False,
            'external_id': '',
            'error': 'No calendar provider configured',
            'calendar_event_id': None,
        }

    provider_impl = _get_provider(provider_key)
    if not provider_impl:
        return {
            'success': False,
            'external_id': '',
            'error': f'Unknown provider: {provider_key}',
            'calendar_event_id': None,
        }

    # Default end time from registry
    if end is None:
        et = get_type(event_type)
        duration = et.default_duration_minutes if et else 60
        end = start + timedelta(minutes=duration)

    # Call provider
    try:
        external_id, error = provider_impl.create_event(
            user=user,
            title=title,
            start=start,
            end=end,
            location=location,
            description=description,
            metadata=context or {},
        )
        success = bool(external_id) and not error
    except Exception as e:
        logger.exception("Calendar push failed for %s", event_type)
        external_id, error, success = '', str(e), False

    status = 'synced' if success else 'failed'

    # Persist
    event_id = _save_event(
        user=user, event_type=event_type, title=title,
        description=description, location=location,
        start=start, end=end, all_day=all_day,
        provider_key=provider_key, external_id=external_id,
        status=status, error=error, metadata=context,
        content_object=content_object, created_by=user,
    )

    _log_sync(
        user=user, event_type=event_type, action='push',
        provider_key=provider_key, success=success, error=error,
    )

    return {
        'success': success,
        'external_id': external_id,
        'error': error,
        'calendar_event_id': event_id,
    }


def update_event(calendar_event_id, title=None, start=None, end=None,
                 location=None, description=None, context=None):
    """Update an existing synced calendar event.

    Args:
        calendar_event_id: UUID of the CalendarEvent record
        **fields: Only provided fields are updated

    Returns:
        dict with keys: success, error
    """
    model_path = getattr(settings, 'KEEL_CALENDAR_EVENT_MODEL', None)
    if not model_path:
        return {'success': False, 'error': 'KEEL_CALENDAR_EVENT_MODEL not configured'}

    try:
        from django.apps import apps
        EventModel = apps.get_model(model_path)
        event = EventModel.objects.get(pk=calendar_event_id)
    except Exception as e:
        return {'success': False, 'error': str(e)}

    provider_impl = _get_provider(event.provider)
    if not provider_impl:
        return {'success': False, 'error': f'Unknown provider: {event.provider}'}

    # Build update fields
    fields = {}
    if title is not None:
        fields['title'] = title
    if start is not None:
        fields['start'] = start
    if end is not None:
        fields['end'] = end
    if location is not None:
        fields['location'] = location
    if description is not None:
        fields['description'] = description

    try:
        success, error = provider_impl.update_event(
            event.external_id, event.user, **fields,
        )
    except Exception as e:
        logger.exception("Calendar update failed for event %s", calendar_event_id)
        success, error = False, str(e)

    # Update local record
    if success:
        for field, value in fields.items():
            model_field = field
            if field == 'start':
                model_field = 'start_time'
            elif field == 'end':
                model_field = 'end_time'
            setattr(event, model_field, value)
        event.last_synced_at = timezone.now()
        event.sync_error = ''
    else:
        event.sync_error = error or ''
        event.status = 'failed'
    event.save()

    _log_sync(
        user=event.user, event_type=event.event_type, action='update',
        provider_key=event.provider, success=success, error=error,
    )

    return {'success': success, 'error': error}


def cancel_event(calendar_event_id):
    """Cancel a synced calendar event.

    Args:
        calendar_event_id: UUID of the CalendarEvent record

    Returns:
        dict with keys: success, error
    """
    model_path = getattr(settings, 'KEEL_CALENDAR_EVENT_MODEL', None)
    if not model_path:
        return {'success': False, 'error': 'KEEL_CALENDAR_EVENT_MODEL not configured'}

    try:
        from django.apps import apps
        EventModel = apps.get_model(model_path)
        event = EventModel.objects.get(pk=calendar_event_id)
    except Exception as e:
        return {'success': False, 'error': str(e)}

    provider_impl = _get_provider(event.provider)
    if not provider_impl:
        return {'success': False, 'error': f'Unknown provider: {event.provider}'}

    try:
        success, error = provider_impl.delete_event(
            event.external_id, event.user,
        )
    except Exception as e:
        logger.exception("Calendar cancel failed for event %s", calendar_event_id)
        success, error = False, str(e)

    event.status = 'cancelled' if success else 'failed'
    event.sync_error = error or ''
    if success:
        event.last_synced_at = timezone.now()
    event.save()

    _log_sync(
        user=event.user, event_type=event.event_type, action='cancel',
        provider_key=event.provider, success=success, error=error,
    )

    return {'success': success, 'error': error}


def check_availability(user, start, end, provider=None):
    """Check if a user is available during a time window.

    Args:
        user: The user to check
        start: Window start datetime
        end: Window end datetime
        provider: Override provider key

    Returns:
        dict with keys: available, conflicts, error
    """
    provider_key = _resolve_provider(provider)
    if not provider_key:
        return {'available': True, 'conflicts': [], 'error': 'No provider configured'}

    provider_impl = _get_provider(provider_key)
    if not provider_impl:
        return {'available': True, 'conflicts': [], 'error': f'Unknown provider: {provider_key}'}

    try:
        available, conflicts, error = provider_impl.check_availability(
            user, start, end,
        )
    except Exception as e:
        logger.exception("Availability check failed for %s", user)
        available, conflicts, error = True, [], str(e)

    _log_sync(
        user=user, event_type='', action='availability',
        provider_key=provider_key, success=not error, error=error,
    )

    return {'available': available, 'conflicts': conflicts, 'error': error}
