"""
Outbound email service — compose, send via Postmark, track delivery.

This is the primary API for products sending email through keel.comms.
"""
import logging

import requests
from django.utils import timezone

from .addresses import generate_message_id
from .conf import COMMS_MAIL_DOMAIN, COMMS_POSTMARK_SERVER_TOKEN
from .models import Message, Thread

logger = logging.getLogger(__name__)

POSTMARK_API_URL = 'https://api.postmarkapp.com/email'


def build_references_chain(in_reply_to_message):
    """Build the References header chain from a parent message.

    Per RFC 5322, References should contain the parent's References
    plus the parent's own Message-ID.
    """
    if not in_reply_to_message:
        return []
    refs = list(in_reply_to_message.references_header or [])
    if in_reply_to_message.message_id_header:
        refs.append(in_reply_to_message.message_id_header)
    return refs


def send_message(
    mailbox,
    thread,
    to,
    subject,
    body_html,
    body_text,
    sent_by,
    cc=None,
    in_reply_to=None,
):
    """Compose and send an outbound email via Postmark.

    Args:
        mailbox: MailboxAddress to send from.
        thread: Thread this message belongs to.
        to: List of recipient email addresses.
        subject: Email subject line.
        body_html: HTML body content.
        body_text: Plain text body content.
        sent_by: User who composed the message.
        cc: Optional list of CC addresses.
        in_reply_to: Optional parent Message (for reply threading).

    Returns:
        The created Message instance.

    Raises:
        PostmarkSendError: If the Postmark API returns an error.
    """
    message_id = generate_message_id(COMMS_MAIL_DOMAIN)
    references = build_references_chain(in_reply_to)

    message = Message.objects.create(
        thread=thread,
        direction=Message.Direction.OUTBOUND,
        from_address=mailbox.address,
        from_name=mailbox.display_name,
        to_addresses=[{'email': addr} for addr in to],
        cc_addresses=[{'email': addr} for addr in (cc or [])],
        reply_to=mailbox.address,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        message_id_header=message_id,
        in_reply_to_header=in_reply_to.message_id_header if in_reply_to else '',
        references_header=references,
        sent_at=timezone.now(),
        sent_by=sent_by,
        delivery_status=Message.DeliveryStatus.PENDING,
    )

    # Build Postmark request
    headers = [
        {'Name': 'Message-ID', 'Value': message_id},
    ]
    if message.in_reply_to_header:
        headers.append({'Name': 'In-Reply-To', 'Value': message.in_reply_to_header})
    if references:
        headers.append({'Name': 'References', 'Value': ' '.join(references)})

    payload = {
        'From': f'{mailbox.display_name} <{mailbox.address}>',
        'To': ', '.join(to),
        'Subject': subject,
        'HtmlBody': body_html,
        'TextBody': body_text,
        'ReplyTo': mailbox.address,
        'Headers': headers,
        'MessageStream': 'outbound',
    }
    if cc:
        payload['Cc'] = ', '.join(cc)

    try:
        resp = requests.post(
            POSTMARK_API_URL,
            json=payload,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Postmark-Server-Token': COMMS_POSTMARK_SERVER_TOKEN,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        message.postmark_message_id = data.get('MessageID', '')
        message.delivery_status = Message.DeliveryStatus.SENT
        message.save(update_fields=['postmark_message_id', 'delivery_status'])

    except requests.RequestException:
        logger.exception('Postmark send failed for message %s', message.pk)
        message.delivery_status = Message.DeliveryStatus.FAILED
        message.save(update_fields=['delivery_status'])
        raise

    # Mark thread as updated
    thread.updated_at = timezone.now()
    thread.save(update_fields=['updated_at'])

    return message


def create_thread(mailbox, subject):
    """Create a new Thread on a mailbox for composing a new conversation."""
    return Thread.objects.create(
        mailbox=mailbox,
        subject=subject,
        is_read=True,
    )
