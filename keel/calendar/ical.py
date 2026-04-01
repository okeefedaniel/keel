"""
iCal (.ics) generation utilities.

No external dependencies — uses manual VCALENDAR string formatting.
The iCalendar format is simple enough to not need a library.

Usage:
    from keel.calendar import generate_ical, generate_single_ical
    from keel.calendar.ical import ical_response

    # Single event download
    response = ical_response(
        generate_single_ical(
            title='CT Innovation Summit',
            start=datetime(2026, 5, 15, 9, 0),
            end=datetime(2026, 5, 15, 17, 0),
            location='Hartford Convention Center',
        ),
        filename='summit.ics',
    )

    # Multiple events from queryset
    events = CalendarEvent.objects.filter(user=request.user)
    ics_string = generate_ical(events, calendar_name='Yeoman')
"""
import uuid
from datetime import datetime

from django.http import HttpResponse


def _format_dt(dt):
    """Format a datetime as iCal YYYYMMDDTHHMMSSZ."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None)  # Convert to UTC-like
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _format_date(dt):
    """Format a date as iCal YYYYMMDD for all-day events."""
    return dt.strftime('%Y%m%d')


def _escape(text):
    """Escape special characters for iCal text values."""
    if not text:
        return ''
    return (
        text.replace('\\', '\\\\')
        .replace(';', '\\;')
        .replace(',', '\\,')
        .replace('\n', '\\n')
    )


def generate_single_ical(title, start, end, location='', description='',
                         uid=None, all_day=False):
    """Generate a single-event .ics string.

    Args:
        title: Event title
        start: datetime for event start
        end: datetime for event end
        location: Physical or virtual location
        description: Event description
        uid: Unique identifier (defaults to random UUID)
        all_day: If True, uses DATE instead of DATETIME

    Returns:
        str: Valid .ics file content
    """
    if uid is None:
        uid = str(uuid.uuid4())

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//DockLabs//Keel Calendar//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f'UID:{uid}',
        f'DTSTAMP:{_format_dt(datetime.utcnow())}',
    ]

    if all_day:
        lines.append(f'DTSTART;VALUE=DATE:{_format_date(start)}')
        lines.append(f'DTEND;VALUE=DATE:{_format_date(end)}')
    else:
        lines.append(f'DTSTART:{_format_dt(start)}')
        lines.append(f'DTEND:{_format_dt(end)}')

    lines.append(f'SUMMARY:{_escape(title)}')

    if location:
        lines.append(f'LOCATION:{_escape(location)}')
    if description:
        lines.append(f'DESCRIPTION:{_escape(description)}')

    lines.extend([
        'END:VEVENT',
        'END:VCALENDAR',
    ])

    return '\r\n'.join(lines) + '\r\n'


def generate_ical(events, calendar_name='DockLabs'):
    """Generate a multi-event .ics string from a queryset or iterable.

    Expects objects with: title, start_time, end_time, location,
    description, id (UUID), all_day.

    Args:
        events: Queryset or iterable of AbstractCalendarEvent instances
        calendar_name: Calendar display name

    Returns:
        str: Valid .ics file content
    """
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        f'PRODID:-//DockLabs//{_escape(calendar_name)}//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:{_escape(calendar_name)}',
    ]

    for event in events:
        lines.append('BEGIN:VEVENT')
        lines.append(f'UID:{event.id}')
        lines.append(f'DTSTAMP:{_format_dt(datetime.utcnow())}')

        if getattr(event, 'all_day', False):
            lines.append(f'DTSTART;VALUE=DATE:{_format_date(event.start_time)}')
            lines.append(f'DTEND;VALUE=DATE:{_format_date(event.end_time)}')
        else:
            lines.append(f'DTSTART:{_format_dt(event.start_time)}')
            lines.append(f'DTEND:{_format_dt(event.end_time)}')

        lines.append(f'SUMMARY:{_escape(event.title)}')

        if event.location:
            lines.append(f'LOCATION:{_escape(event.location)}')
        if event.description:
            lines.append(f'DESCRIPTION:{_escape(event.description)}')

        lines.append('END:VEVENT')

    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'


def ical_response(ics_content, filename='event.ics'):
    """Wrap .ics content in a Django HttpResponse for download.

    Args:
        ics_content: String output from generate_ical or generate_single_ical
        filename: Download filename

    Returns:
        HttpResponse with Content-Type text/calendar
    """
    response = HttpResponse(ics_content, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
