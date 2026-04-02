"""Notification channel dispatchers."""
from .in_app import send_in_app
from .email import send_email
from .sms import send_sms
from .boswell import send_boswell

CHANNELS = {
    'in_app': send_in_app,
    'email': send_email,
    'sms': send_sms,
    'boswell': send_boswell,
}

__all__ = ['CHANNELS', 'send_in_app', 'send_email', 'send_sms', 'send_boswell']
