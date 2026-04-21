"""Outbound client for the Manifest signing handoff.

Three entry points:

    is_available()
        True when Manifest is configured (MANIFEST_URL + token). Use in
        templates and views to gate "Send for Signing" controls per the
        standalone-deployability rule in keel/CLAUDE.md — do not render
        controls that silently no-op when Manifest is absent.

    send_to_manifest(source_obj, ...)
        Creates a ManifestHandoff row and best-effort POSTs to Manifest.
        Returns the ManifestHandoff. On network failure the row is
        marked FAILED and the caller's action still succeeds.

    local_sign(source_obj, signed_pdf, ...)
        Standalone fallback when Manifest isn't deployed. Records a
        handoff row with status=LOCAL_SIGNED and fires packet_approved
        so the source product's receiver files the PDF and transitions
        status the same way it would for a real Manifest roundtrip.

Products subclass nothing — they call these functions and connect a
receiver to ``signals.packet_approved``. The helpers intentionally stay
small; the per-product dedup of the existing harbor/manifest signing
services is a separate piece of work (see keel/signatures/__init__.py).
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from .models import ManifestHandoff
from .signals import packet_approved

logger = logging.getLogger(__name__)


def is_available() -> bool:
    """True when Manifest is deployed and configured for this product."""
    return bool(
        getattr(settings, 'MANIFEST_URL', '')
        and getattr(settings, 'MANIFEST_API_TOKEN', '')
    )


def send_to_manifest(
    *,
    source_obj: Any,
    packet_label: str,
    signers: list[dict],
    attachment_model: str,
    attachment_fk_name: str,
    on_approved_status: str,
    initial_document_url: str | None = None,
    created_by=None,
    callback_url: str | None = None,
) -> ManifestHandoff:
    """Kick off a Manifest signing packet for ``source_obj``.

    Writes a ManifestHandoff row first (so we always have a local record
    of the attempt) and then best-effort POSTs to Manifest. A failure to
    reach Manifest does not block the caller — the row is saved as
    FAILED with an error message the UI can surface.
    """
    handoff = ManifestHandoff.objects.create(
        source_app_label=source_obj._meta.app_label,
        source_model=source_obj._meta.model_name,
        source_pk=str(source_obj.pk),
        attachment_model=attachment_model,
        attachment_fk_name=attachment_fk_name,
        on_approved_status=on_approved_status,
        packet_label=packet_label,
        created_by=created_by,
    )

    if not is_available():
        handoff.status = ManifestHandoff.Status.FAILED
        handoff.error_message = 'Manifest is not configured for this deployment.'
        handoff.save(update_fields=['status', 'error_message', 'updated_at'])
        return handoff

    try:
        import requests  # imported lazily — only required when Manifest is reachable
    except ImportError:  # pragma: no cover
        handoff.status = ManifestHandoff.Status.FAILED
        handoff.error_message = 'The requests package is not installed.'
        handoff.save(update_fields=['status', 'error_message', 'updated_at'])
        return handoff

    payload = {
        'handoff_id': str(handoff.id),
        'label': packet_label,
        'signers': signers,
        'initial_document_url': initial_document_url,
        'callback_url': callback_url,
        'source': handoff.source_label,
    }
    url = settings.MANIFEST_URL.rstrip('/') + '/api/v1/signing/packets/'
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={'Authorization': f'Token {settings.MANIFEST_API_TOKEN}'},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        handoff.manifest_packet_uuid = data.get('packet_uuid', '')
        handoff.manifest_url = data.get('packet_url', '')
        handoff.status = ManifestHandoff.Status.SENT
        handoff.save(update_fields=[
            'manifest_packet_uuid', 'manifest_url', 'status', 'updated_at',
        ])
    except Exception as exc:  # noqa: BLE001 — want the full error chain
        logger.warning('send_to_manifest failed: %s', exc)
        handoff.status = ManifestHandoff.Status.FAILED
        handoff.error_message = str(exc)[:500]
        handoff.save(update_fields=['status', 'error_message', 'updated_at'])
    return handoff


def complete_handoff(handoff: ManifestHandoff, signed_pdf) -> None:
    """Finalize a handoff and fire ``packet_approved``.

    Shared between the inbound webhook and ``local_sign`` so the source
    product's receiver sees the same signal either way.
    """
    from django.utils import timezone
    source_obj = handoff.resolve_source()
    handoff.status = ManifestHandoff.Status.SIGNED if handoff.status != ManifestHandoff.Status.LOCAL_SIGNED else handoff.status
    handoff.signed_at = timezone.now()
    handoff.save(update_fields=['status', 'signed_at', 'updated_at'])
    packet_approved.send(
        sender=type(source_obj),
        handoff=handoff,
        source_obj=source_obj,
        signed_pdf=signed_pdf,
    )


def local_sign(
    *,
    source_obj: Any,
    signed_pdf,
    attachment_model: str,
    attachment_fk_name: str,
    on_approved_status: str,
    packet_label: str = '',
    created_by=None,
) -> ManifestHandoff:
    """Record a locally-signed approval when Manifest isn't deployed.

    The signed PDF is attached and the source is transitioned via the
    same ``packet_approved`` signal the real Manifest roundtrip fires.
    """
    handoff = ManifestHandoff.objects.create(
        source_app_label=source_obj._meta.app_label,
        source_model=source_obj._meta.model_name,
        source_pk=str(source_obj.pk),
        attachment_model=attachment_model,
        attachment_fk_name=attachment_fk_name,
        on_approved_status=on_approved_status,
        packet_label=packet_label,
        status=ManifestHandoff.Status.LOCAL_SIGNED,
        created_by=created_by,
    )
    complete_handoff(handoff, signed_pdf)
    return handoff
