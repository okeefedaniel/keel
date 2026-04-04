"""Comms configuration — all settings read from Django settings with defaults."""

from django.conf import settings

COMMS_MAIL_DOMAIN = getattr(settings, 'COMMS_MAIL_DOMAIN', 'mail.docklabs.ai')
COMMS_POSTMARK_SERVER_TOKEN = getattr(settings, 'COMMS_POSTMARK_SERVER_TOKEN', '')
COMMS_POSTMARK_WEBHOOK_TOKEN = getattr(settings, 'COMMS_POSTMARK_WEBHOOK_TOKEN', '')
