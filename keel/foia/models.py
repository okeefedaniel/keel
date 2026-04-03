"""
Keel FOIA Models — Cross-product FOIA compliance infrastructure.

This module provides the AbstractFOIAExportItem model — the universal queue
that lets any DockLabs product export records for FOIA review in Admiralty.

The FOIA *workflow* models (AbstractFOIARequest, AbstractFOIAScope,
AbstractFOIASearchResult, AbstractFOIADetermination, AbstractFOIAResponsePackage,
AbstractFOIAAppeal, AbstractStatutoryExemption) live in Admiralty, the standalone
FOIA request management product (github.com/okeefedaniel/admiralty).

Usage in a product:
    from keel.foia.models import AbstractFOIAExportItem

    class FOIAExportItem(AbstractFOIAExportItem):
        class Meta(AbstractFOIAExportItem.Meta):
            pass
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# FOIAExportItem — cross-product queue for FOIA record export
# ---------------------------------------------------------------------------
class AbstractFOIAExportItem(models.Model):
    """A record exported from any DockLabs product for FOIA review.

    This is the cross-product queue. Products write to it, Admiralty reads
    from it. Each product creates a concrete subclass:

        class FOIAExportItem(AbstractFOIAExportItem):
            class Meta(AbstractFOIAExportItem.Meta):
                pass
    """

    class ReviewStatus(models.TextChoices):
        PENDING = 'pending', _('Pending Review')
        RESPONSIVE = 'responsive', _('Responsive')
        NOT_RESPONSIVE = 'not_responsive', _('Not Responsive')
        PARTIALLY_RESPONSIVE = 'partial', _('Partially Responsive')
        EXEMPT = 'exempt', _('Exempt')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Source tracking
    source_product = models.CharField(max_length=50, db_index=True)
    record_type = models.CharField(max_length=50, db_index=True)
    record_id = models.CharField(max_length=200)

    # Content for review
    title = models.CharField(max_length=500)
    content = models.TextField()
    content_hash = models.CharField(
        max_length=64, db_index=True,
        help_text=_('SHA256 hash for deduplication.'),
    )

    # Metadata
    created_by_name = models.CharField(max_length=200, blank=True)
    record_created_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    # Export tracking
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_foia_exports',
    )
    submitted_from_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text=_('IP address of the staff member who submitted this export.'),
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    # FOIA linkage (set by Admiralty when processing)
    foia_request_id_ref = models.CharField(
        max_length=200, blank=True, db_index=True,
        help_text=_('FK reference to FOIARequest in Admiralty (stored as string to avoid cross-DB FK).'),
    )

    # Review status
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['source_product', 'record_type']),
            models.Index(fields=['review_status']),
            models.Index(fields=['content_hash']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['source_product', 'record_type', 'record_id', 'foia_request_id_ref'],
                name='%(app_label)s_unique_foia_export',
            ),
        ]

    def __str__(self):
        return f"[{self.source_product}] {self.title} ({self.get_review_status_display()})"
