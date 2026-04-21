"""Inbound completion webhook.

Manifest POSTs here on packet completion. The payload names the handoff
UUID and a URL to the signed PDF; we download the PDF, look up the
ManifestHandoff, and fire ``packet_approved`` for the source product's
receiver to attach and transition.

Webhook authentication is by shared secret ``MANIFEST_WEBHOOK_SECRET``,
sent in the ``X-Manifest-Signature`` header as ``sha256=<hmac-hex>``.
Products that don't configure the secret reject all inbound webhooks.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from io import BytesIO

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .client import complete_handoff
from .models import ManifestHandoff

logger = logging.getLogger(__name__)


def _verify_signature(body: bytes, header: str) -> bool:
    secret = getattr(settings, 'MANIFEST_WEBHOOK_SECRET', '')
    if not secret or not header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    prefix = 'sha256='
    if not header.startswith(prefix):
        return False
    return hmac.compare_digest(expected, header[len(prefix):])


@csrf_exempt
@require_POST
def webhook(request):
    if not _verify_signature(
        request.body,
        request.META.get('HTTP_X_MANIFEST_SIGNATURE', ''),
    ):
        return HttpResponseForbidden('invalid signature')

    try:
        payload = json.loads(request.body.decode())
    except json.JSONDecodeError:
        return HttpResponseBadRequest('invalid json')

    handoff_id = payload.get('handoff_id') or ''
    packet_uuid = payload.get('packet_uuid') or ''
    signed_pdf_url = payload.get('signed_pdf_url') or ''

    handoff = None
    if handoff_id:
        handoff = ManifestHandoff.objects.filter(pk=handoff_id).first()
    if handoff is None and packet_uuid:
        handoff = ManifestHandoff.objects.filter(manifest_packet_uuid=packet_uuid).first()

    if handoff is None:
        return HttpResponseBadRequest('unknown handoff')

    if handoff.status == ManifestHandoff.Status.SIGNED:
        # Idempotent — Manifest may retry. Acknowledge without re-firing.
        return HttpResponse(status=200)

    # Download the signed PDF so the source product can file it on the
    # object's Attachment collection in one shot.
    try:
        import requests
        pdf_resp = requests.get(signed_pdf_url, timeout=30)
        pdf_resp.raise_for_status()
        signed_pdf = BytesIO(pdf_resp.content)
        signed_pdf.name = f'{handoff.packet_label or "signed"}.pdf'
    except Exception as exc:  # noqa: BLE001
        logger.exception('Failed to download signed PDF for handoff %s: %s', handoff.pk, exc)
        handoff.status = ManifestHandoff.Status.FAILED
        handoff.error_message = f'Signed PDF download failed: {exc}'[:500]
        handoff.save(update_fields=['status', 'error_message', 'updated_at'])
        return HttpResponse(status=502)

    handoff.signed_pdf_url = signed_pdf_url
    handoff.manifest_packet_uuid = packet_uuid or handoff.manifest_packet_uuid
    handoff.save(update_fields=[
        'signed_pdf_url', 'manifest_packet_uuid', 'updated_at',
    ])
    complete_handoff(handoff, signed_pdf)
    return HttpResponse(status=200)
