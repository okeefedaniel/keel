"""Django email backend using the Resend HTTP API.

Railway blocks outbound SMTP, so we use Resend's HTTPS API instead.

We bypass the official ``resend`` Python SDK and POST directly to
``api.resend.com`` so we can control the User-Agent header. The SDK hardcodes
``User-Agent: resend-python:<version>``, which Cloudflare in front of the
Resend API has been observed to fingerprint-ban (HTTP 403, error 1010) on
some Railway egress IPs — including keel.docklabs.ai's. Sending a benign
browser-style UA sidesteps the filter.

Settings:
    EMAIL_BACKEND = 'keel.notifications.backends.resend_backend.ResendEmailBackend'
    RESEND_API_KEY = 're_...'
    DEFAULT_FROM_EMAIL = 'DockLabs <info@docklabs.ai>'
"""
import base64
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = 'https://api.resend.com/emails'
USER_AGENT = 'DockLabs-Keel/1.0 (+https://keel.docklabs.ai)'


class ResendEmailBackend(BaseEmailBackend):
    """Send emails via Resend's HTTP API."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, 'RESEND_API_KEY', '')

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        if not self.api_key:
            logger.error('Resend backend invoked but RESEND_API_KEY is not set')
            if not self.fail_silently:
                raise RuntimeError('RESEND_API_KEY is not configured')
            return 0

        sent = 0
        for message in email_messages:
            try:
                payload = self._build_payload(message)
                self._post(payload)
                sent += 1
                logger.debug('Resend email sent to %s', message.to)
            except Exception as e:
                logger.error('Resend email failed to %s: %s', message.to, e)
                if not self.fail_silently:
                    raise
        return sent

    def _build_payload(self, message):
        payload = {
            'from': message.from_email or settings.DEFAULT_FROM_EMAIL,
            'to': list(message.to),
            'subject': message.subject,
        }

        html_body = None
        if hasattr(message, 'alternatives') and message.alternatives:
            for content, mimetype in message.alternatives:
                if mimetype == 'text/html':
                    html_body = content
                    break
        if html_body is not None:
            payload['html'] = html_body
        else:
            payload['text'] = message.body

        if message.cc:
            payload['cc'] = list(message.cc)
        if message.bcc:
            payload['bcc'] = list(message.bcc)
        if message.reply_to:
            payload['reply_to'] = message.reply_to[0]

        if message.attachments:
            payload['attachments'] = [
                self._format_attachment(a) for a in message.attachments
            ]
        return payload

    @staticmethod
    def _format_attachment(attachment):
        if not (isinstance(attachment, tuple) and len(attachment) >= 2):
            raise ValueError('Unsupported attachment shape')
        filename, content = attachment[0], attachment[1]
        mimetype = attachment[2] if len(attachment) > 2 else None
        if isinstance(content, bytes):
            encoded = base64.b64encode(content).decode('ascii')
        else:
            encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
        out = {'filename': filename, 'content': encoded}
        if mimetype:
            out['content_type'] = mimetype
        return out

    def _post(self, payload):
        body = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            RESEND_ENDPOINT,
            data=body,
            method='POST',
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:500]
            except Exception:
                pass
            raise RuntimeError(
                f'Resend API returned HTTP {e.code}: {detail}'
            ) from e
