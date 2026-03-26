"""Django email backend using the Resend HTTP API.

Railway blocks outbound SMTP, so we use Resend's Python SDK instead.

Settings:
    EMAIL_BACKEND = 'keel.notifications.backends.resend_backend.ResendEmailBackend'
    RESEND_API_KEY = 're_...'
    DEFAULT_FROM_EMAIL = 'noreply@send.docklabs.ai'
"""
import logging

import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    """Send emails via Resend HTTP API."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        resend.api_key = getattr(settings, 'RESEND_API_KEY', '')

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sent = 0
        for message in email_messages:
            try:
                params = {
                    'from': message.from_email or settings.DEFAULT_FROM_EMAIL,
                    'to': list(message.to),
                    'subject': message.subject,
                }

                # Use HTML body if available, otherwise plain text
                if hasattr(message, 'alternatives') and message.alternatives:
                    for content, mimetype in message.alternatives:
                        if mimetype == 'text/html':
                            params['html'] = content
                            break
                    if 'html' not in params:
                        params['text'] = message.body
                else:
                    params['text'] = message.body

                if message.cc:
                    params['cc'] = list(message.cc)
                if message.bcc:
                    params['bcc'] = list(message.bcc)
                if message.reply_to:
                    params['reply_to'] = message.reply_to[0]

                result = resend.Emails.send(params)
                sent += 1
                logger.debug('Resend email sent to %s (id: %s)', message.to, result)

            except Exception as e:
                logger.error('Resend email failed to %s: %s', message.to, e)
                if not self.fail_silently:
                    raise

        return sent
