"""Local back-pointer tracking for Manifest signing handoffs.

``ManifestHandoff`` lives in the *source* product's database. It links
a source object (by app_label + model + pk triple, since products and
Manifest may run on separate Postgres instances) to a Manifest
``SigningPacket`` (by UUID). One row per handoff attempt.

When Manifest completes a packet it POSTs to the source product's
``/keel/signatures/webhook/`` endpoint with the packet UUID and a URL
to the signed PDF. The view looks up the matching ``ManifestHandoff``
row, fires the ``packet_approved`` signal, and the source product's
receiver attaches the PDF to its ``Attachment`` collection and
transitions the source object's status to approved.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ManifestHandoff(models.Model):
    """One row per "send to Manifest for signing" attempt."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending — not yet sent to Manifest')
        SENT = 'sent', _('Sent to Manifest; awaiting signatures')
        SIGNED = 'signed', _('Completed; signed PDF returned')
        FAILED = 'failed', _('Send to Manifest failed')
        LOCAL_SIGNED = 'local_signed', _('Locally signed (Manifest unavailable)')
        CANCELLED = 'cancelled', _('Cancelled before completion')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Source object identity — strings, not FKs, because products may
    # live in separate databases from each other and from Manifest.
    source_app_label = models.CharField(max_length=64)
    source_model = models.CharField(max_length=64)
    source_pk = models.CharField(max_length=64)

    # Where on the source model to file the signed PDF. Format is
    # "app_label.ModelName"; must be an AbstractAttachment subclass.
    attachment_model = models.CharField(max_length=128)
    # Name of the FK field on that attachment model that points at the
    # source object. The default matches bounty's "tracked_opportunity"
    # naming; harbor's equivalent is "application".
    attachment_fk_name = models.CharField(max_length=64)

    # Target status to transition the source object to on completion.
    on_approved_status = models.CharField(max_length=64)

    # Cross-product back-pointer to the Manifest packet. String, not FK.
    # Blank until the outbound POST succeeds.
    manifest_packet_uuid = models.CharField(max_length=64, blank=True)
    manifest_url = models.URLField(blank=True)

    # Human-facing label shown in the Manifest dashboard.
    packet_label = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    error_message = models.TextField(blank=True)

    # URL to the signed PDF (hosted by Manifest) once complete.
    signed_pdf_url = models.URLField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='manifest_handoffs_initiated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('Manifest Handoff')
        verbose_name_plural = _('Manifest Handoffs')
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['source_app_label', 'source_model', 'source_pk'],
                name='kls_handoff_source_idx',
            ),
            models.Index(fields=['manifest_packet_uuid'], name='kls_handoff_packet_idx'),
        ]

    def __str__(self):
        return f"Handoff {self.id} — {self.source_model}:{self.source_pk} ({self.get_status_display()})"

    @property
    def source_label(self):
        return f"{self.source_app_label}.{self.source_model}:{self.source_pk}"

    def resolve_source(self):
        """Return the live source object this handoff is linked to."""
        from django.apps import apps
        model = apps.get_model(self.source_app_label, self.source_model)
        return model.objects.get(pk=self.source_pk)
