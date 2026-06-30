"""
Webhook endpoints for Resend and htmx views for the comms panel.
"""
import email as email_lib
import json
import logging
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from . import resend_client
from .conf import COMMS_RESEND_API_KEY, COMMS_RESEND_WEBHOOK_SECRET
from .export import export_message_eml_response, export_thread_transcript_response
from .models import Attachment, DeadLetter, MailboxAddress, Message, Thread
from .registry import comms_registry
from .routing import parse_address, resolve_thread
from .sanitize import sanitize_html
from .search import comms_search
from .services import create_thread, send_message


def _user_can_access_mailbox(user, mailbox) -> bool:
    """Enforce cross-tenant isolation on comms.

    Threads leak by UUID (email headers, search results, notification
    URLs). Without this check, any ``is_staff`` user on any product could
    read / export any thread from any mailbox on any product.

    Superusers retain access. Otherwise, the user must hold an active
    ``ProductAccess`` row for the mailbox's ``product``.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    product = getattr(mailbox, 'product', None)
    if not product:
        return False
    has_access = getattr(user, 'has_product_access', None)
    if callable(has_access):
        return bool(has_access(product))
    # Fallback for non-KeelUser (should not happen in prod): deny.
    return False


def _mailbox_for_user_or_404(user, mailbox_id):
    mailbox = get_object_or_404(MailboxAddress, pk=mailbox_id, is_active=True)
    if not _user_can_access_mailbox(user, mailbox):
        from django.http import Http404
        raise Http404('mailbox not found')
    return mailbox


def _thread_for_user_or_404(user, thread_id, *, mailbox=None):
    qs = Thread.objects.select_related('mailbox')
    if mailbox is not None:
        qs = qs.filter(mailbox=mailbox)
    thread = get_object_or_404(qs, pk=thread_id)
    if not _user_can_access_mailbox(user, thread.mailbox):
        from django.http import Http404
        raise Http404('thread not found')
    return thread

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resend webhook (single endpoint — Resend posts every event type here)
# ---------------------------------------------------------------------------
def _verify_webhook(request):
    """Verify the Svix signature on a Resend webhook.

    Fails closed: if COMMS_RESEND_WEBHOOK_SECRET is unset, every request is
    rejected. The secret is the endpoint signing secret from the Resend
    dashboard (``whsec_...``).
    """
    if not COMMS_RESEND_WEBHOOK_SECRET:
        logger.error('Comms: COMMS_RESEND_WEBHOOK_SECRET not configured — rejecting webhook')
        return False
    return resend_client.verify_webhook_signature(
        COMMS_RESEND_WEBHOOK_SECRET, request.headers, request.body,
    )


# Resend delivery-event types → DeliveryStatus.
_DELIVERY_EVENTS = {
    'email.sent': Message.DeliveryStatus.SENT,
    'email.delivered': Message.DeliveryStatus.DELIVERED,
    'email.bounced': Message.DeliveryStatus.BOUNCED,
    'email.failed': Message.DeliveryStatus.FAILED,
}


@csrf_exempt
@require_POST
def resend_webhook(request):
    """Receive all Resend events (inbound mail + outbound delivery status).

    POST /keel/comms/webhook/resend/
    """
    if not _verify_webhook(request):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        logger.warning('Comms: invalid JSON in resend webhook')
        return JsonResponse({'status': 'invalid_payload'}, status=400)

    event_type = payload.get('type', '')
    data = payload.get('data', {}) or {}

    if event_type == 'email.received':
        return _handle_inbound(data)

    if event_type in _DELIVERY_EVENTS:
        return _handle_delivery_event(event_type, data, payload)

    # Other event types (e.g. email.opened) — ack so Resend stops retrying.
    return JsonResponse({'status': 'ignored', 'event': event_type}, status=200)


def _handle_delivery_event(event_type, data, payload):
    """Reconcile an outbound message's delivery status from a Resend event."""
    email_id = data.get('email_id') or data.get('id') or ''
    if not email_id:
        return JsonResponse({'status': 'no_message_id'}, status=200)

    status = _DELIVERY_EVENTS[event_type]
    update = {'delivery_status': status}
    if status in (Message.DeliveryStatus.BOUNCED, Message.DeliveryStatus.FAILED):
        update['delivery_detail'] = payload

    updated = Message.objects.filter(provider_message_id=email_id).update(**update)
    return JsonResponse({'status': 'ok', 'updated': updated})


def _handle_inbound(data):
    """Handle a Resend ``email.received`` event.

    The webhook carries metadata only, so we fetch the full content (body,
    headers, attachments) from the Received-emails API by ``email_id``.
    """
    email_id = data.get('email_id', '')
    if not email_id:
        logger.warning('Comms: email.received with no email_id')
        return JsonResponse({'status': 'no_email_id'}, status=400)

    try:
        full = resend_client.get_received_email(COMMS_RESEND_API_KEY, email_id)
    except resend_client.ResendError:
        logger.exception('Comms: failed to fetch received email %s', email_id)
        # 200 so Resend doesn't retry-storm; the dead letter records the miss.
        _dead_letter(data, reason=DeadLetter.Reason.PARSE_ERROR)
        return JsonResponse({'status': 'fetch_failed'}, status=200)

    # Route on the address the mail was received for (catch-all target),
    # falling back to scanning To/Cc for a structured mailbox address.
    parsed = None
    candidates = [full.get('received_for', '')]
    candidates += list(full.get('to') or []) + list(full.get('cc') or [])
    for cand in candidates:
        if not cand:
            continue
        _, addr = parseaddr(cand if isinstance(cand, str) else cand.get('email', ''))
        parsed = parse_address(addr)
        if parsed:
            break

    if not parsed:
        _dead_letter(full, reason=DeadLetter.Reason.UNROUTABLE)
        return JsonResponse({'status': 'unroutable'}, status=200)

    try:
        mailbox = MailboxAddress.objects.get(address=parsed.raw, is_active=True)
    except MailboxAddress.DoesNotExist:
        _dead_letter(full, reason=DeadLetter.Reason.NO_MAILBOX)
        return JsonResponse({'status': 'no_mailbox'}, status=200)

    headers = _header_map(full.get('headers'))
    in_reply_to = headers.get('in-reply-to', '')
    references_raw = headers.get('references', '')
    references = references_raw.split() if references_raw else []

    message_id_header = full.get('message_id') or headers.get('message-id', '')
    if not message_id_header:
        import uuid
        message_id_header = f'<resend-{uuid.uuid4()}@inbound>'

    # Deduplicate — Resend retries on 5xx.
    if Message.objects.filter(message_id_header=message_id_header).exists():
        return JsonResponse({'status': 'duplicate'}, status=200)

    thread = resolve_thread(
        mailbox=mailbox,
        in_reply_to=in_reply_to,
        references=references,
        subject=full.get('subject', ''),
    )

    date_str = headers.get('date', '')
    sent_at = None
    if date_str:
        try:
            sent_at = parsedate_to_datetime(date_str)
        except (TypeError, ValueError):
            sent_at = None
    if sent_at is None:
        sent_at = timezone.now()
    if timezone.is_naive(sent_at):
        sent_at = timezone.make_aware(sent_at)

    from_name, from_email = parseaddr(full.get('from', ''))
    raw_html = full.get('html', '') or ''
    safe_html = sanitize_html(raw_html) if raw_html else ''

    message = Message.objects.create(
        thread=thread,
        direction=Message.Direction.INBOUND,
        from_address=from_email,
        from_name=from_name,
        to_addresses=_address_dicts(full.get('to')),
        cc_addresses=_address_dicts(full.get('cc')),
        subject=full.get('subject', ''),
        body_text=full.get('text', '') or '',
        body_html=safe_html,
        message_id_header=message_id_header,
        in_reply_to_header=in_reply_to,
        references_header=references,
        sent_at=sent_at,
        delivery_status=Message.DeliveryStatus.DELIVERED,
    )

    Thread.objects.filter(pk=thread.pk).update(
        is_read=False,
        updated_at=timezone.now(),
    )

    _save_inbound_attachments(message, full)

    comms_registry.dispatch(
        product=parsed.product,
        entity_type=parsed.entity_type,
        message=message,
        mailbox=mailbox,
    )

    return JsonResponse({'status': 'ok'})


def _header_map(headers):
    """Normalize Resend's ``headers`` (dict or list) to a lowercased dict."""
    out = {}
    if isinstance(headers, dict):
        for k, v in headers.items():
            out[str(k).lower()] = v
    elif isinstance(headers, list):
        for h in headers:
            if isinstance(h, dict):
                name = h.get('name') or h.get('Name')
                if name:
                    out[str(name).lower()] = h.get('value') or h.get('Value')
    return out


def _address_dicts(values):
    """Normalize a Resend address list (strings) to ``[{name, email}]``."""
    if not values:
        return []
    pairs = getaddresses([v for v in values if isinstance(v, str)])
    return [{'name': n, 'email': e} for n, e in pairs if e]


# ---------------------------------------------------------------------------
# htmx UI views (staff only)
# ---------------------------------------------------------------------------
@staff_member_required
@require_GET
def comms_panel(request, mailbox_id):
    """Render the communications panel for a mailbox.

    GET /keel/comms/<mailbox_id>/
    """
    mailbox = _mailbox_for_user_or_404(request.user, mailbox_id)
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
    thread = _thread_for_user_or_404(request.user, thread_id)
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
    mailbox = _mailbox_for_user_or_404(request.user, mailbox_id)
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
    mailbox = _mailbox_for_user_or_404(request.user, mailbox_id)

    to_raw = request.POST.get('to', '')
    to_list = [addr.strip() for addr in to_raw.split(',') if addr.strip()]
    subject = request.POST.get('subject', '')
    body_text = request.POST.get('body', '')
    # HTML-escape the user-supplied body before wrapping in <pre>; an f-string
    # here would let a staff user inject arbitrary HTML into outbound mail that
    # ships via Resend under a trusted .gov sender.
    body_html = format_html(
        '<pre style="font-family: sans-serif;">{}</pre>', body_text,
    )

    cc_raw = request.POST.get('cc', '')
    cc_list = [addr.strip() for addr in cc_raw.split(',') if addr.strip()] or None

    # Reply or new thread?
    thread_id = request.POST.get('thread_id')
    in_reply_to = None
    if thread_id:
        thread = _thread_for_user_or_404(request.user, thread_id, mailbox=mailbox)
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
    message = get_object_or_404(
        Message.objects.select_related('thread__mailbox'),
        pk=message_id,
    )
    if not _user_can_access_mailbox(request.user, message.thread.mailbox):
        from django.http import Http404
        raise Http404('message not found')
    return export_message_eml_response(message)


@staff_member_required
@require_GET
def export_thread(request, thread_id):
    """Download a thread as a plain text transcript.

    GET /keel/comms/export/thread/<thread_id>/
    """
    thread = _thread_for_user_or_404(request.user, thread_id)
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
    user = request.user
    for msg in results.select_related('thread__mailbox'):
        # Filter cross-tenant results: only include messages whose mailbox
        # the user has product access to. Prevents search from leaking
        # thread UUIDs across products.
        if not _user_can_access_mailbox(user, msg.thread.mailbox):
            continue
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
    """Store an unroutable message for manual triage.

    ``payload`` is a Resend webhook ``data`` object or a fetched received-email
    body — both expose ``from`` (string), ``to`` (list), and ``subject``.
    """
    _, from_email = parseaddr(payload.get('from', '') or '')
    to_list = payload.get('to') or []
    to_address = ''
    if to_list:
        _, to_address = parseaddr(to_list[0] if isinstance(to_list[0], str) else '')

    DeadLetter.objects.create(
        raw_payload=payload,
        from_address=from_email,
        to_address=to_address,
        subject=payload.get('subject', ''),
        reason=reason,
    )


_FILENAME_ALLOWED = set(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'
)


def _sanitize_attachment_filename(name: str) -> str:
    """Return a safe on-disk filename for an inbound attachment.

    Strips path separators, control chars, and anything outside a
    conservative allowlist; preserves a single ``.ext`` suffix; truncates
    to 64 chars total. An unusable name collapses to ``attachment``.
    """
    if not name:
        return 'attachment'
    # Drop any directory components before filtering.
    name = name.replace('\\', '/').rsplit('/', 1)[-1]
    # Strip null bytes + control chars + anything off the allowlist.
    cleaned = ''.join(c if c in _FILENAME_ALLOWED else '_' for c in name).strip('._')
    if not cleaned:
        return 'attachment'
    # Truncate keeping the final extension if present.
    if len(cleaned) > 64:
        stem, dot, ext = cleaned.rpartition('.')
        if dot and len(ext) <= 8:
            keep = 64 - len(ext) - 1
            cleaned = f'{stem[:keep]}.{ext}'
        else:
            cleaned = cleaned[:64]
    return cleaned


def _save_inbound_attachments(message, full):
    """Save inbound attachments for a received email.

    Resend's webhook + received-email JSON expose attachment *metadata* only;
    the bytes live in the original message, fetched once via the signed
    ``raw.download_url`` and parsed with the stdlib email parser. Skips the
    download entirely when the message has no attachments.
    """
    attachments_meta = full.get('attachments') or []
    if not attachments_meta:
        return

    raw_url = (full.get('raw') or {}).get('download_url', '')
    if not raw_url:
        logger.warning(
            'Comms: message %s has %d attachment(s) but no raw.download_url',
            message.pk, len(attachments_meta),
        )
        return

    try:
        raw_bytes = resend_client.download_bytes(raw_url)
    except resend_client.ResendError:
        logger.exception('Comms: failed to download raw email for message %s', message.pk)
        return

    parsed = email_lib.message_from_bytes(raw_bytes)
    for part in parsed.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        filename = part.get_filename()
        disposition = (part.get('Content-Disposition') or '').lower()
        if not filename and 'attachment' not in disposition:
            continue
        try:
            file_bytes = part.get_payload(decode=True)
        except Exception:
            file_bytes = None
        if not file_bytes:
            continue
        _store_attachment_bytes(
            message,
            raw_name=filename or 'attachment',
            content_type=part.get_content_type() or 'application/octet-stream',
            file_bytes=file_bytes,
        )


def _store_attachment_bytes(message, raw_name, content_type, file_bytes):
    """Validate and persist one inbound attachment's bytes.

    The ``raw_name`` is attacker-controlled, so it is passed through
    ``_sanitize_attachment_filename`` before being used as a storage path.
    Extensions are validated against ``KEEL_ALLOWED_UPLOAD_EXTENSIONS`` (if
    configured) — unknown extensions are dropped rather than silently stored.
    """
    from django.conf import settings as _settings

    filename = _sanitize_attachment_filename(raw_name)

    allowed_exts = getattr(_settings, 'KEEL_ALLOWED_UPLOAD_EXTENSIONS', None)
    if allowed_exts:
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in {e.lower().lstrip('.') for e in allowed_exts}:
            logger.warning(
                'Comms: rejected attachment with disallowed extension '
                '%s on message %s', ext, message.pk,
            )
            return

    # Optional content scan — the keel FileSecurityValidator covers magic
    # bytes and (when enabled) ClamAV. We invoke it on a wrapped buffer so
    # it can raise ValidationError without forcing a model FileField.
    try:
        from django.core.files.uploadedfile import SimpleUploadedFile
        from keel.security.scanning import FileSecurityValidator

        validator = FileSecurityValidator()
        validator(SimpleUploadedFile(filename, file_bytes, content_type=content_type))
    except Exception as exc:  # ValidationError or ImportError (optional dep)
        logger.warning(
            'Comms: FileSecurityValidator rejected attachment %s: %s',
            filename, exc,
        )
        return

    attachment = Attachment(
        message=message,
        filename=filename,
        content_type=content_type,
        size_bytes=len(file_bytes),
    )
    attachment.file.save(filename, ContentFile(file_bytes), save=False)
    attachment.save()
