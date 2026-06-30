"""Comms configuration — all settings read from Django settings with defaults."""

from django.conf import settings

COMMS_MAIL_DOMAIN = getattr(settings, 'COMMS_MAIL_DOMAIN', 'mail.docklabs.ai')

# keel.comms sends and receives through Resend, sharing the suite-wide
# Resend account with keel.notifications (single vendor — no Postmark).
#
# - Outbound send and the inbound content/attachment fetches reuse the
#   suite-wide ``RESEND_API_KEY``.
# - Inbound webhooks are Svix-signed; ``COMMS_RESEND_WEBHOOK_SECRET`` is the
#   endpoint's signing secret from the Resend dashboard (``whsec_...``).
#   Inbound fails closed when it is unset.
COMMS_RESEND_API_KEY = getattr(settings, 'RESEND_API_KEY', '')
COMMS_RESEND_WEBHOOK_SECRET = getattr(settings, 'COMMS_RESEND_WEBHOOK_SECRET', '')
