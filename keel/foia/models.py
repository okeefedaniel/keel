"""
Keel FOIA Models — Abstract base classes for FOIA compliance.

These models define the complete FOIA workflow data model.
Products inherit from these and can add domain-specific fields.

Usage in a product:
    from keel.foia.models import (
        AbstractStatutoryExemption, AbstractFOIARequest, AbstractFOIAScope,
        AbstractFOIASearchResult, AbstractFOIADetermination,
        AbstractFOIAResponsePackage, AbstractFOIAAppeal,
    )

    class StatutoryExemption(AbstractStatutoryExemption):
        class Meta(AbstractStatutoryExemption.Meta):
            pass

    class FOIARequest(AbstractFOIARequest):
        # Add product-specific fields
        related_companies = models.ManyToManyField('companies.Company', blank=True)
        class Meta(AbstractFOIARequest.Meta):
            pass
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .validators import validate_document_file


# ---------------------------------------------------------------------------
# StatutoryExemption
# ---------------------------------------------------------------------------
class AbstractStatutoryExemption(models.Model):
    """Reference table of statutory FOIA exemptions (e.g., CT \u00a7 1-210)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subdivision = models.CharField(
        max_length=20,
        help_text=_('e.g. 1-210(b)(5)(A)'),
    )
    label = models.CharField(max_length=255)
    statutory_text = models.TextField()
    citation = models.CharField(max_length=255)
    guidance_notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['subdivision']

    def __str__(self):
        return f"{self.subdivision} - {self.label}"


# ---------------------------------------------------------------------------
# FOIARequest
# ---------------------------------------------------------------------------
class AbstractFOIARequest(models.Model):
    """A Freedom of Information Act request."""

    class Status(models.TextChoices):
        RECEIVED = 'received', _('Received')
        SCOPE_DEFINED = 'scope_defined', _('Scope Defined')
        SEARCHING = 'searching', _('Searching')
        UNDER_REVIEW = 'under_review', _('Under Review')
        PACKAGE_READY = 'package_ready', _('Package Ready')
        SENIOR_REVIEW = 'senior_review', _('Senior Review')
        RESPONDED = 'responded', _('Responded')
        APPEALED = 'appealed', _('Appealed')
        CLOSED = 'closed', _('Closed')

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        NORMAL = 'normal', _('Normal')
        HIGH = 'high', _('High')
        URGENT = 'urgent', _('Urgent')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RECEIVED,
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.NORMAL,
    )

    # Requester info
    requester_name = models.CharField(max_length=255)
    requester_email = models.EmailField(blank=True)
    requester_phone = models.CharField(max_length=20, blank=True)
    requester_organization = models.CharField(max_length=255, blank=True)
    requester_address = models.TextField(blank=True)

    # Request content
    subject = models.CharField(max_length=500)
    description = models.TextField()
    original_request_text = models.TextField(blank=True)

    # Dates & deadlines
    date_received = models.DateField()
    statutory_deadline = models.DateField(
        null=True, blank=True,
        help_text=_('4 business days from receipt per CT FOIA'),
    )
    extended_deadline = models.DateField(null=True, blank=True)
    date_responded = models.DateField(null=True, blank=True)
    date_closed = models.DateField(null=True, blank=True)

    # Assignment
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_assigned_foia',
    )
    reviewing_attorney = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_reviewing_foia',
    )

    # Tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_created_foia',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-date_received']

    def __str__(self):
        return f"{self.request_number} - {self.subject[:60]}"


# ---------------------------------------------------------------------------
# FOIAScope
# ---------------------------------------------------------------------------
class AbstractFOIAScope(models.Model):
    """Defines search parameters for a FOIA request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Note: concrete model must add `foia_request` FK
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)
    keywords = models.JSONField(
        default=list, blank=True,
        help_text=_('Search keywords'),
    )
    company_names = models.JSONField(
        default=list, blank=True,
        help_text=_('Company names to search'),
    )
    contact_names = models.JSONField(
        default=list, blank=True,
        help_text=_('Contact names to search'),
    )
    record_types = models.JSONField(
        default=list, blank=True,
        help_text=_('Types of records to search (notes, interactions, etc.)'),
    )
    scope_notes = models.TextField(blank=True)
    defined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    defined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"Scope ({self.pk})"


# ---------------------------------------------------------------------------
# FOIASearchResult
# ---------------------------------------------------------------------------
class AbstractFOIASearchResult(models.Model):
    """A record found during FOIA search that needs review."""

    class PreClassification(models.TextChoices):
        LIKELY_RESPONSIVE = 'likely_responsive', _('Likely Responsive')
        LIKELY_EXEMPT = 'likely_exempt', _('Likely Exempt')
        NEEDS_REVIEW = 'needs_review', _('Needs Review')
        NOT_RELEVANT = 'not_relevant', _('Not Relevant')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Note: concrete model must add `foia_request` FK

    # Record reference
    record_type = models.CharField(max_length=50, help_text=_('e.g. note, interaction, document'))
    record_id = models.UUIDField()
    record_description = models.TextField(blank=True)

    # Snapshot
    snapshot_content = models.TextField(blank=True)
    snapshot_metadata = models.JSONField(default=dict, blank=True)
    snapshot_taken_at = models.DateTimeField(auto_now_add=True)

    # Pre-classification
    pre_classification = models.CharField(
        max_length=20, choices=PreClassification.choices,
        default=PreClassification.NEEDS_REVIEW,
    )
    classification_reason = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ['record_type', 'snapshot_taken_at']

    def __str__(self):
        return f"{self.record_type} ({self.record_id}) - {self.get_pre_classification_display()}"


# ---------------------------------------------------------------------------
# FOIADetermination
# ---------------------------------------------------------------------------
class AbstractFOIADetermination(models.Model):
    """Legal determination for a FOIA search result."""

    class Decision(models.TextChoices):
        RELEASE = 'release', _('Release')
        WITHHOLD = 'withhold', _('Withhold')
        PARTIAL_RELEASE = 'partial_release', _('Partial Release')
        REFER = 'refer', _('Refer to Another Agency')

    class ExemptionReview(models.TextChoices):
        NOT_REVIEWED = 'not_reviewed', _('Not Reviewed')
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')
        NEEDS_REVISION = 'needs_revision', _('Needs Revision')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Note: concrete model must add `search_result` FK and `exemptions_claimed` M2M

    decision = models.CharField(max_length=20, choices=Decision.choices)
    exemption_review = models.CharField(
        max_length=20, choices=ExemptionReview.choices,
        default=ExemptionReview.NOT_REVIEWED,
    )
    justification = models.TextField(blank=True)
    redacted_content = models.TextField(blank=True)

    # Attorney metadata
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_foia_determinations',
    )
    attorney_notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"Determination: {self.get_decision_display()}"


# ---------------------------------------------------------------------------
# FOIAResponsePackage
# ---------------------------------------------------------------------------
class AbstractFOIAResponsePackage(models.Model):
    """The compiled response package for a FOIA request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Note: concrete model must add `foia_request` FK

    # Generated files
    cover_letter = models.FileField(upload_to='foia_responses/%Y/%m/', blank=True, validators=[validate_document_file])
    response_file = models.FileField(upload_to='foia_responses/%Y/%m/', blank=True, validators=[validate_document_file])
    privilege_log = models.FileField(upload_to='foia_responses/%Y/%m/', blank=True, validators=[validate_document_file])

    # Summary stats
    total_records_found = models.PositiveIntegerField(default=0)
    records_released = models.PositiveIntegerField(default=0)
    records_withheld = models.PositiveIntegerField(default=0)
    records_partially_released = models.PositiveIntegerField(default=0)

    # Compliance
    is_complete = models.BooleanField(default=False)
    is_reviewed_by_attorney = models.BooleanField(default=False)
    is_approved_by_senior = models.BooleanField(default=False)

    generated_at = models.DateTimeField(null=True, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"Response Package ({self.pk})"


# ---------------------------------------------------------------------------
# FOIAAppeal
# ---------------------------------------------------------------------------
class AbstractFOIAAppeal(models.Model):
    """An appeal filed against a FOIA response."""

    class AppealStatus(models.TextChoices):
        FILED = 'filed', _('Filed')
        HEARING_SCHEDULED = 'hearing_scheduled', _('Hearing Scheduled')
        HEARING_COMPLETED = 'hearing_completed', _('Hearing Completed')
        DECISION_PENDING = 'decision_pending', _('Decision Pending')
        UPHELD = 'upheld', _('Upheld (Agency Decision Stands)')
        OVERTURNED = 'overturned', _('Overturned')
        SETTLED = 'settled', _('Settled')
        WITHDRAWN = 'withdrawn', _('Withdrawn')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Note: concrete model must add `foia_request` FK

    appeal_status = models.CharField(
        max_length=25, choices=AppealStatus.choices, default=AppealStatus.FILED,
    )

    # Appeal details
    appeal_number = models.CharField(max_length=50, blank=True)
    filed_date = models.DateField()
    appellant_arguments = models.TextField(blank=True)
    agency_response = models.TextField(blank=True)

    # Hearing
    hearing_date = models.DateField(null=True, blank=True)
    hearing_notes = models.TextField(blank=True)

    # Decision
    decision_date = models.DateField(null=True, blank=True)
    decision_summary = models.TextField(blank=True)
    decision_document = models.FileField(
        upload_to='foia_appeals/%Y/%m/', blank=True,
        validators=[validate_document_file],
    )

    # Lessons learned
    lessons_learned = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-filed_date']

    def __str__(self):
        return f"Appeal {self.appeal_number or self.id} - {self.get_appeal_status_display()}"
