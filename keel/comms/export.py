"""
Message and thread export for FOIA records requests.

All messages in keel.comms are government records. This module provides
export in standard formats for records retention and FOIA compliance.

Supported formats:
    - .eml (RFC 5322 Internet Message Format) — individual messages
    - .txt (plain text transcript) — full thread export
"""
import io
from email.message import EmailMessage
from email.utils import format_datetime

from django.http import HttpResponse

from .models import Message, Thread


def message_to_eml(message: Message) -> str:
    """Convert a Message to RFC 5322 .eml format."""
    eml = EmailMessage()

    eml['From'] = (
        f'{message.from_name} <{message.from_address}>'
        if message.from_name else message.from_address
    )

    # To addresses
    to_list = []
    for addr in (message.to_addresses or []):
        if isinstance(addr, dict):
            email = addr.get('email') or addr.get('Email', '')
            name = addr.get('name') or addr.get('Name', '')
            to_list.append(f'{name} <{email}>' if name else email)
        else:
            to_list.append(str(addr))
    if to_list:
        eml['To'] = ', '.join(to_list)

    # CC addresses
    cc_list = []
    for addr in (message.cc_addresses or []):
        if isinstance(addr, dict):
            email = addr.get('email') or addr.get('Email', '')
            cc_list.append(email)
        else:
            cc_list.append(str(addr))
    if cc_list:
        eml['Cc'] = ', '.join(cc_list)

    eml['Subject'] = message.subject
    eml['Date'] = format_datetime(message.sent_at)
    eml['Message-ID'] = message.message_id_header

    if message.in_reply_to_header:
        eml['In-Reply-To'] = message.in_reply_to_header
    if message.references_header:
        eml['References'] = ' '.join(message.references_header)

    # Body — prefer text, include HTML as alternative
    if message.body_text and message.body_html:
        eml.make_alternative()
        eml.add_alternative(message.body_text, subtype='plain')
        eml.add_alternative(message.body_html, subtype='html')
    elif message.body_html:
        eml.set_content(message.body_html, subtype='html')
    else:
        eml.set_content(message.body_text or '')

    return eml.as_string()


def thread_to_transcript(thread: Thread) -> str:
    """Export a thread as a plain text transcript.

    Includes all messages in chronological order with metadata.
    Suitable for records requests where .eml is not needed.
    """
    lines = []
    lines.append(f'Thread: {thread.subject}')
    lines.append(f'Mailbox: {thread.mailbox.address}')
    lines.append(f'Entity: {thread.mailbox.display_name}')
    lines.append(f'Created: {thread.created_at.isoformat()}')
    lines.append('=' * 72)
    lines.append('')

    messages = thread.messages.order_by('sent_at')
    for msg in messages:
        direction = 'RECEIVED' if msg.direction == Message.Direction.INBOUND else 'SENT'
        lines.append(f'--- {direction} ---')
        lines.append(f'Date: {msg.sent_at.isoformat()}')
        lines.append(f'From: {msg.from_name} <{msg.from_address}>' if msg.from_name else f'From: {msg.from_address}')

        to_strs = []
        for addr in (msg.to_addresses or []):
            if isinstance(addr, dict):
                to_strs.append(addr.get('email') or addr.get('Email', ''))
            else:
                to_strs.append(str(addr))
        if to_strs:
            lines.append(f'To: {", ".join(to_strs)}')

        lines.append(f'Subject: {msg.subject}')

        if msg.direction == Message.Direction.OUTBOUND and msg.sent_by:
            lines.append(f'Sent by: {msg.sent_by.get_full_name()} ({msg.sent_by.email})')

        lines.append(f'Delivery: {msg.get_delivery_status_display()}')
        lines.append('')
        lines.append(msg.body_text or '(no text body)')
        lines.append('')

        # Note attachments
        attachments = msg.attachments.all()
        if attachments:
            lines.append(f'Attachments ({attachments.count()}):')
            for att in attachments:
                lines.append(f'  - {att.filename} ({att.content_type}, {att.size_bytes} bytes)')
            lines.append('')

        lines.append('')

    return '\n'.join(lines)


def _safe_download_header(basename: str) -> str:
    """Return a Content-Disposition value safe against CRLF/filename tricks.

    Strips control characters and quotes, then urllib-quotes to emit an
    RFC 5987 ``filename*`` param alongside an ASCII fallback.
    """
    from urllib.parse import quote as _urlquote

    cleaned = ''.join(c for c in basename if c.isprintable() and c not in '"\r\n\\')
    ascii_fallback = ''.join(c if ord(c) < 128 else '_' for c in cleaned) or 'download'
    encoded = _urlquote(cleaned, safe='')
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{encoded}"
    )


def export_message_eml_response(message: Message) -> HttpResponse:
    """Return an HttpResponse with a single message as .eml download."""
    eml_content = message_to_eml(message)
    response = HttpResponse(eml_content, content_type='message/rfc822')
    safe_subject = message.subject[:50].replace(' ', '_').replace('/', '-')
    response['Content-Disposition'] = _safe_download_header(f'{safe_subject}.eml')
    return response


def export_thread_transcript_response(thread: Thread) -> HttpResponse:
    """Return an HttpResponse with a thread transcript as .txt download."""
    transcript = thread_to_transcript(thread)
    response = HttpResponse(transcript, content_type='text/plain; charset=utf-8')
    safe_subject = thread.subject[:50].replace(' ', '_').replace('/', '-')
    response['Content-Disposition'] = _safe_download_header(
        f'{safe_subject}_transcript.txt'
    )
    return response
