"""Compliance obligation tracking for DockLabs products.

Product-agnostic compliance engine using GenericForeignKey so any
product can attach compliance requirements to its domain objects:

  - Purser attaches to Programs (monthly close compliance)
  - Harbor attaches to Awards/Grants (grant compliance)
  - Any future product with contractual obligations

One compliance engine, multiple product views.
"""
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from keel.core.models import KeelBaseModel


class ComplianceTemplate(KeelBaseModel):
    """Defines a type of compliance requirement that can be
    attached to contracts/grants/programs.

    Examples:
    - "Quarterly Progress Report" (document, quarterly)
    - "Annual Audited Financials" (document, annual)
    - "Job Creation Milestone — Year 1" (milestone, one-time)
    - "Site Visit Certification" (document, annual)
    """

    class RequirementType(models.TextChoices):
        DOCUMENT = 'document', _('Document Submission')
        MILESTONE = 'milestone', _('Milestone Achievement')
        CERTIFICATION = 'certification', _('Certification/Attestation')
        FINANCIAL_REPORT = 'financial_report', _('Financial Report')

    class Cadence(models.TextChoices):
        ONE_TIME = 'one_time', _('One-Time')
        MONTHLY = 'monthly', _('Monthly')
        QUARTERLY = 'quarterly', _('Quarterly')
        SEMI_ANNUAL = 'semi_annual', _('Semi-Annual')
        ANNUAL = 'annual', _('Annual')
        CUSTOM = 'custom', _('Custom Schedule')

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    requirement_type = models.CharField(
        max_length=30, choices=RequirementType.choices,
    )
    cadence = models.CharField(max_length=20, choices=Cadence.choices)

    # How many days before due date to start sending reminders
    reminder_lead_days = models.PositiveIntegerField(default=14)
    # How many days after due date before escalation
    escalation_after_days = models.PositiveIntegerField(default=7)

    # Document requirements
    requires_document = models.BooleanField(default=True)
    accepted_file_types = models.CharField(max_length=200, blank=True)  # "pdf,xlsx,docx"

    # Which role can mark this as satisfied (product-specific role string)
    reviewer_role = models.CharField(max_length=50, default='compliance_officer')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ComplianceObligation(KeelBaseModel):
    """A specific compliance requirement on a specific entity.

    Uses GenericForeignKey for both program and recipient so any
    product can use compliance tracking:

    - Purser: program → purser.Program, recipient → keel_accounts.Agency
    - Harbor: program → awards.Award, recipient → core.Organization
    """

    template = models.ForeignKey(
        ComplianceTemplate, on_delete=models.CASCADE,
        related_name='obligations',
    )

    # GenericFK: the program/grant/award this obligation belongs to
    program_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE,
        related_name='+', null=True, blank=True,
    )
    program_object_id = models.CharField(max_length=255, blank=True)
    program = GenericForeignKey('program_content_type', 'program_object_id')

    # GenericFK: the recipient organization responsible for compliance
    recipient_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE,
        related_name='+', null=True, blank=True,
    )
    recipient_object_id = models.CharField(max_length=255, blank=True)
    recipient = GenericForeignKey('recipient_content_type', 'recipient_object_id')

    # Contract reference
    contract_number = models.CharField(max_length=100, blank=True)
    contract_date = models.DateField(null=True, blank=True)

    # Schedule
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    custom_due_dates = models.JSONField(default=list, blank=True)
    # For custom cadence: ["2026-01-15", "2026-04-15", ...]

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['start_date']

    def __str__(self):
        return f"{self.template.name} — {self.contract_number or 'no contract'}"


class ComplianceItem(KeelBaseModel):
    """A single due instance of a compliance obligation.

    Auto-generated from the obligation's cadence. One row per due date.

    Example: "WidgetCo Q3 FY2026 Progress Report — due Apr 15, 2026"

    Status workflow:
    pending → submitted → under_review → accepted / rejected → overdue (auto)
    """

    class Status(models.TextChoices):
        UPCOMING = 'upcoming', _('Upcoming')
        PENDING = 'pending', _('Pending — Due Soon')
        SUBMITTED = 'submitted', _('Submitted — Awaiting Review')
        UNDER_REVIEW = 'under_review', _('Under Review')
        ACCEPTED = 'accepted', _('Accepted')
        REJECTED = 'rejected', _('Rejected — Resubmission Required')
        OVERDUE = 'overdue', _('Overdue')
        WAIVED = 'waived', _('Waived')

    obligation = models.ForeignKey(
        ComplianceObligation, on_delete=models.CASCADE,
        related_name='items',
    )
    fiscal_period = models.ForeignKey(
        'keel_periods.FiscalPeriod', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='compliance_items',
    )
    label = models.CharField(max_length=200)            # "Q3 FY2026 Progress Report"
    due_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPCOMING,
    )

    # Submission tracking
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='compliance_submissions',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    document = models.FileField(
        upload_to='compliance/documents/%Y/%m/', blank=True,
    )

    # Review
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='compliance_reviews',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_notes = models.TextField(blank=True)

    # Notifications sent (for dedup)
    last_reminder_sent = models.DateTimeField(null=True, blank=True)
    escalation_sent = models.BooleanField(default=False)

    class Meta:
        unique_together = ['obligation', 'due_date']
        ordering = ['due_date']

    def __str__(self):
        return f"{self.label} — due {self.due_date}"
