"""
Webhook endpoints for Postmark and htmx views for the comms panel.
"""
import base64
import json
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .conf import COMMS_POSTMARK_WEBHOOK_TOKEN
from .export import export_message_eml_response, export_thread_transcript_response
from .models import Attachment, DeadLetter, MailboxAddress, Message, Thread
from .registry import comms_registry
from .routing import parse_address, resolve_thread
from .sanitize import sanitize_html
from .search import comms_search
from .services import create_thread, send_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook authentication
# ---------------------------------------------------------------------------
def _verify_webhook(request):
    """Verify the inbound webhook using a shared token.

    Postmark doesn't sign payloads, so we use a secret token
    passed as a query parameter or Authorization header.
    """
    if not COMMS_POSTMARK_WEBHOOK_TOKEN:
        return True  # No token configured — allow (dev mode)

    # Check Authorization header first
    auth = request.headers.get('Authorization', '')
    if auth == f'Bearer {COMMS_POSTMARK_WEBHOOK_TOKEN}':
        return True

    # Check query parameter fallback
    if request.GET.get('token') == COMMS_POSTMARK_WEBHOOK_TOKEN:
        return True

    return False


# ---------------------------------------------------------------------------
# Postmark inbound webhook
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def postmark_inbound_webhook(request):
    """Receive inbound email from Postmark.

    POST /keel/comms/webhook/postmark/inbound/
    """
    if not _verify_webhook(request):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        logger.warning('Comms: invalid JSON in inbound webhook')
        return JsonResponse({'status': 'invalid_payload'}, status=400)

    # Extract recipient address
    to_full = payload.get('ToFull', [])
    if not to_full:
        _dead_letter(payload, reason=DeadLetter.Reason.PARSE_ERROR)
        return JsonResponse({'status': 'no_recipient'}, status=200)

    to_address = to_full[0].get('Email', '')
    parsed = parse_address(to_address)

    if not parsed:
        _dead_letter(payload, reason=DeadLetter.Reason.UNROUTABLE)
        return JsonResponse({'status': 'unroutable'}, status=200)

    # Resolve mailbox
    try:
        mailbox = MailboxAddress.objects.get(address=parsed.raw, is_active=True)
    except MailboxAddress.DoesNotExist:
        _dead_letter(payload, reason=DeadLetter.Reason.NO_MAILBOX)
        return JsonResponse({'status': 'no_mailbox'}, status=200)

    # Thread resolution
    headers = {
        h['Name']: h['Value']
        for h in payload.get('Headers', [])
        if isinstance(h, dict)
    }
    in_reply_to = headers.get('In-Reply-To', '')
    references_raw = headers.get('References', '')
    references = references_raw.split() if references_raw else []

    thread = resolve_thread(
        mailbox=mailbox,
        in_reply_to=in_reply_to,
        references=references,
        subject=payload.get('Subject', ''),
    )

    # Determine sent_at
    date_str = payload.get('Date')
    sent_at = parse_datetime(date_str) if date_str else timezone.now()
    if sent_at and timezone.is_naive(sent_at):
        sent_at = timezone.make_aware(sent_at)

    # Create message
    message_id_header = payload.get('MessageID', '') or headers.get('Message-ID', '')
    if not message_id_header:
        import uuid
        message_id_header = f'<postmark-{uuid.uuid4()}@inbound>'

    # Deduplicate — if we've already processed this Message-ID, skip
    if Message.objects.filter(message_id_header=message_id_header).exists():
        return JsonResponse({'status': 'duplicate'}, status=200)

    from_full = payload.get('FromFull', {})

    # Sanitize inbound HTML to prevent XSS in the comms panel
    raw_html = payload.get('HtmlBody', '')
    safe_html = sanitize_html(raw_html) if raw_html else ''

    message = Message.objects.create(
        thread=thread,
        direction=Message.Direction.INBOUND,
        from_address=from_full.get('Email', payload.get('From', '')),
        from_name=from_full.get('Name', ''),
        to_addresses=payload.get('ToFull', []),
        cc_addresses=payload.get('CcFull', []),
        subject=payload.get('Subject', ''),
        body_text=payload.get('TextBody', ''),
        body_html=safe_html,
        message_id_header=message_id_header,
        in_reply_to_header=in_reply_to,
        references_header=references,
        sent_at=sent_at,
        delivery_status=Message.DeliveryStatus.DELIVERED,
    )

    # Mark thread as unread + bump timestamp
    Thread.objects.filter(pk=thread.pk).update(
        is_read=False,
        updated_at=timezone.now(),
    )

    # Save attachments
    for att_data in payload.get('Attachments', []):
        _save_attachment(message, att_data)

    # Dispatch to product handler
    comms_registry.dispatch(
        product=parsed.product,
        entity_type=parsed.entity_type,
        message=message,
        mailbox=mailbox,
    )

    return JsonResponse({'status': 'ok'})


# ---------------------------------------------------------------------------
# Postmark delivery / bounce webhooks
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def postmark_delivery_webhook(request):
    """Track delivery confirmations from Postmark.

    POST /keel/comms/webhook/postmark/delivery/
    """
    if not _verify_webhook(request):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'invalid_payload'}, status=400)

    pm_message_id = payload.get('MessageID', '')
    if not pm_message_id:
        return JsonResponse({'status': 'no_message_id'}, status=200)

    updated = Message.objects.filter(
        postmark_message_id=pm_message_id,
    ).update(
        delivery_status=Message.DeliveryStatus.DELIVERED,
    )

    return JsonResponse({'status': 'ok', 'updated': updated})


@csrf_exempt
@require_POST
def postmark_bounce_webhook(request):
    """Track bounces from Postmark.

    POST /keel/comms/webhook/postmark/bounce/
    """
    if not _verify_webhook(request):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'invalid_payload'}, status=400)

    pm_message_id = payload.get('MessageID', '')
    if not pm_message_id:
        return JsonResponse({'status': 'no_message_id'}, status=200)

    Message.objects.filter(
        postmark_message_id=pm_message_id,
    ).update(
        delivery_status=Message.DeliveryStatus.BOUNCED,
        delivery_detail=payload,
    )

    return JsonResponse({'status': 'ok'})


# ---------------------------------------------------------------------------
# htmx UI views (staff only)
# ---------------------------------------------------------------------------
@staff_member_required
@require_GET
def comms_panel(request, mailbox_id):
    """Render the communications panel for a mailbox.

    GET /keel/comms/<mailbox_id>/
    """
    mailbox = get_object_or_404(MailboxAddress, pk=mailbox_id, is_active=True)
    threads = mailbox.threads.filter(is_archived=False).order_by('-updated_at')

    return render(request, 'comms/_panel.html', {
        'mailbox': mailbox,
        'threads': threads,
    })


@staff_member_required
@require_GET
def thread_detail(request, thread_id):
    """Render a single thread's messages.

    GET /keel/comms/thread/<thread_id>/
    """
    thread = get_object_or_404(Thread, pk=thread_id)
    messages = thread.messages.select_related('sent_by').prefetch_related('attachments')

    # Mark as read
    if not thread.is_read:
        Thread.objects.filter(pk=thread.pk).update(is_read=True)

    return render(request, 'comms/_thread_detail.html', {
        'thread': thread,
        'messages': messages,
        'mailbox': thread.mailbox,
    })


@staff_member_required
@require_GET
def compose_form(request, mailbox_id):
    """Render the compose / reply form.

    GET /keel/comms/<mailbox_id>/compose/
    GET /keel/comms/<mailbox_id>/compose/?reply_to=<thread_id>
    """
    mailbox = get_object_or_404(MailboxAddress, pk=mailbox_id, is_active=True)
    reply_thread = None
    reply_message = None

    thread_id = request.GET.get('reply_to')
    if thread_id:
        reply_thread = Thread.objects.filter(pk=thread_id, mailbox=mailbox).first()
        if reply_thread:
            reply_message = reply_thread.messages.order_by('-sent_at').first()

    return render(request, 'comms/_compose.html', {
        'mailbox': mailbox,
        'reply_thread': reply_thread,
        'reply_message': reply_message,
    })


@staff_member_required
@require_POST
def send_compose(request, mailbox_id):
    """Handle compose form submission.

    POST /keel/comms/<mailbox_id>/send/
    """
    mailbox = get_object_or_404(MailboxAddress, pk=mailbox_id, is_active=True)

    to_raw = request.POST.get('to', '')
    to_list = [addr.strip() for addr in to_raw.split(',') if addr.strip()]
    subject = request.POST.get('subject', '')
    body_text = request.POST.get('body', '')
    body_html = f'<pre style="font-family: sans-serif;">{body_text}</pre>'

    cc_raw = request.POST.get('cc', '')
    cc_list = [addr.strip() for addr in cc_raw.split(',') if addr.strip()] or None

    # Reply or new thread?
    thread_id = request.POST.get('thread_id')
    in_reply_to = None
    if thread_id:
        thread = get_object_or_404(Thread, pk=thread_id, mailbox=mailbox)
        in_reply_to = thread.messages.order_by('-sent_at').first()
    else:
        thread = create_thread(mailbox, subject)

    message = send_message(
        mailbox=mailbox,
        thread=thread,
        to=to_list,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        sent_by=request.user,
        cc=cc_list,
        in_reply_to=in_reply_to,
    )

    # Return the updated thread view
    messages_qs = thread.messages.select_related('sent_by').prefetch_related('attachments')
    return render(request, 'comms/_thread_detail.html', {
        'thread': thread,
        'messages': messages_qs,
        'mailbox': mailbox,
        'just_sent': True,
    })


# ---------------------------------------------------------------------------
# Export views (FOIA compliance)
# ---------------------------------------------------------------------------
@staff_member_required
@require_GET
def export_message(request, message_id):
    """Download a single message as .eml.

    GET /keel/comms/export/message/<message_id>/
    """
    message = get_object_or_404(Message, pk=message_id)
    return export_message_eml_response(message)


@staff_member_required
@require_GET
def export_thread(request, thread_id):
    """Download a thread as a plain text transcript.

    GET /keel/comms/export/thread/<thread_id>/
    """
    thread = get_object_or_404(Thread, pk=thread_id)
    return export_thread_transcript_response(thread)


# ---------------------------------------------------------------------------
# Search view
# ---------------------------------------------------------------------------
@staff_member_required
@require_GET
def search_messages(request):
    """Search messages via full-text search.

    GET /keel/comms/search/?q=...&product=...&direction=...
    Returns JSON results for htmx or API consumption.
    """
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'results': [], 'count': 0})

    filters = {}
    if request.GET.get('product'):
        filters['product'] = request.GET['product']
    if request.GET.get('direction'):
        filters['direction'] = request.GET['direction']
    if request.GET.get('mailbox_id'):
        filters['mailbox_id'] = request.GET['mailbox_id']

    results = comms_search.search(query, filters=filters, limit=50)
    data = []
    for msg in results.select_related('thread__mailbox'):
        data.append({
            'id': str(msg.pk),
            'subject': msg.subject,
            'from_address': msg.from_address,
            'from_name': msg.from_name,
            'direction': msg.direction,
            'sent_at': msg.sent_at.isoformat(),
            'thread_id': str(msg.thread_id),
            'mailbox_address': msg.thread.mailbox.address,
            'snippet': (msg.body_text or '')[:200],
        })

    return JsonResponse({'results': data, 'count': len(data)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dead_letter(payload, reason):
    """Store an unroutable message for manual triage."""
    from_full = payload.get('FromFull', {})
    to_full = payload.get('ToFull', [{}])

    DeadLetter.objects.create(
        raw_payload=payload,
        from_address=from_full.get('Email', payload.get('From', '')),
        to_address=to_full[0].get('Email', '') if to_full else '',
        subject=payload.get('Subject', ''),
        reason=reason,
    )


def _save_attachment(message, att_data):
    """Save a Postmark attachment to an Attachment record."""
    content = att_data.get('Content', '')
    if not content:
        return

    try:
        file_bytes = base64.b64decode(content)
    except Exception:
        logger.warning('Failed to decode attachment for message %s', message.pk)
        return

    filename = att_data.get('Name', 'attachment')
    content_type = att_data.get('ContentType', 'application/octet-stream')

    attachment = Attachment(
        message=message,
        filename=filename,
        content_type=content_type,
        size_bytes=len(file_bytes),
    )
    attachment.file.save(filename, ContentFile(file_bytes), save=False)
    attachment.save()
