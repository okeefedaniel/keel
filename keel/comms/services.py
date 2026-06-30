"""
Outbound email service — compose, send via Resend, track delivery.

This is the primary API for products sending email through keel.comms.
"""
import logging

from django.utils import timezone

from . import resend_client
from .addresses import generate_message_id
from .conf import COMMS_MAIL_DOMAIN, COMMS_RESEND_API_KEY
from .models import Message, Thread

logger = logging.getLogger(__name__)


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
    """Compose and send an outbound email via Resend.

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
        resend_client.ResendError: If the Resend API returns an error.
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

    # Build Resend request. Resend's `headers` is an object, and it accepts
    # custom Message-ID / In-Reply-To / References so external clients thread
    # replies back onto this conversation.
    headers = {'Message-ID': message_id}
    if message.in_reply_to_header:
        headers['In-Reply-To'] = message.in_reply_to_header
    if references:
        headers['References'] = ' '.join(references)

    payload = {
        'from': f'{mailbox.display_name} <{mailbox.address}>',
        'to': list(to),
        'subject': subject,
        'html': body_html,
        'text': body_text,
        'reply_to': mailbox.address,
        'headers': headers,
    }
    if cc:
        payload['cc'] = list(cc)

    try:
        data = resend_client.send_email(COMMS_RESEND_API_KEY, payload)

        message.provider_message_id = data.get('id', '')
        message.delivery_status = Message.DeliveryStatus.SENT
        message.save(update_fields=['provider_message_id', 'delivery_status'])

    except resend_client.ResendError:
        logger.exception('Resend send failed for message %s', message.pk)
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
