"""SMS notification channel via Twilio.

Configuration:
    KEEL_SMS_BACKEND = 'twilio'  # or None to disable
    TWILIO_ACCOUNT_SID = 'ACxxxxx'
    TWILIO_AUTH_TOKEN = 'xxxxx'
    TWILIO_FROM_NUMBER = '+1xxxxxxxxxx'

Users must have a `phone` field on their User model to receive SMS.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(recipient, title, message, link='', priority='medium',
             notification_type='', **kwargs):
    """Send an SMS notification via Twilio.

    Only sends if:
    1. KEEL_SMS_BACKEND is set to 'twilio'
    2. Twilio credentials are configured
    3. Recipient has a phone number

    Args:
        recipient: User instance (must have .phone attribute).
        title: Notification title.
        message: Message body (truncated to 1600 chars for SMS).
        link: URL path to append.
        priority: Priority level.
        notification_type: Registry key.

    Returns:
        (success: bool, error_message: str)
    """
    backend = getattr(settings, 'KEEL_SMS_BACKEND', None)
    if not backend:
        return False, 'SMS backend not configured (KEEL_SMS_BACKEND not set)'

    phone = getattr(recipient, 'phone', None)
    if not phone:
        return False, 'Recipient has no phone number'

    # Normalize phone number
    phone = _normalize_phone(phone)
    if not phone:
        return False, 'Invalid phone number format'

    if backend == 'twilio':
        return _send_twilio(phone, title, message, link)
    else:
        return False, f'Unknown SMS backend: {backend}'


def _send_twilio(phone, title, message, link):
    """Send via Twilio REST API."""
    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '')

    if not all([account_sid, auth_token, from_number]):
        return False, 'Twilio credentials not configured'

    try:
        from twilio.rest import Client
    except ImportError:
        return False, 'twilio package not installed — pip install twilio'

    # Compose SMS body (keep under 1600 chars)
    from .email import build_absolute_url
    body = f'{title}\n\n{message}'
    if link:
        body += f'\n\n{build_absolute_url(link)}'
    body = body[:1600]

    try:
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=body,
            from_=from_number,
            to=phone,
        )
        return True, ''
    except Exception as e:
        logger.exception('Failed to send SMS to %s', phone)
        return False, str(e)


def _normalize_phone(phone):
    """Normalize a phone number to E.164 format for Twilio.

    Handles common US formats:
    - (860) 555-0100 → +18605550100
    - 860-555-0100 → +18605550100
    - 8605550100 → +18605550100
    - +18605550100 → +18605550100
    """
    import re

    if not phone:
        return None

    # Strip everything except digits and leading +
    digits = re.sub(r'[^\d+]', '', phone)

    if digits.startswith('+'):
        return digits  # Already E.164

    # US numbers
    if len(digits) == 10:
        return f'+1{digits}'
    elif len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'

    # Can't normalize — return None
    return None
