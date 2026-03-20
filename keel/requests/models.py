"""Change request models — beta user feedback pipeline.

A ChangeRequest represents a user-submitted suggestion or bug report.
It flows through: Pending → Approved/Declined → Implemented.

When approved, a Claude Code prompt is auto-generated from the request
details + admin notes, ready for copy-paste execution.
"""
import uuid
from textwrap import dedent

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Category(models.TextChoices):
    BUG = 'bug', _('Bug Report')
    FEATURE = 'feature', _('Feature Request')
    UI = 'ui', _('UI/UX Improvement')
    DATA = 'data', _('Data/Report Request')
    WORKFLOW = 'workflow', _('Workflow Change')
    OTHER = 'other', _('Other')


class Priority(models.TextChoices):
    LOW = 'low', _('Low')
    MEDIUM = 'medium', _('Medium')
    HIGH = 'high', _('High')
    CRITICAL = 'critical', _('Critical')


class Status(models.TextChoices):
    PENDING = 'pending', _('Pending Review')
    APPROVED = 'approved', _('Approved')
    DECLINED = 'declined', _('Declined')
    IMPLEMENTING = 'implementing', _('Implementing')
    IMPLEMENTED = 'implemented', _('Implemented')


# Map product names to repo directories for prompt generation
PRODUCT_PATHS = {
    'beacon': '~/SynologyDrive/Work/CT/Web/beacon',
    'harbor': '~/SynologyDrive/Work/CT/Web/harbor',
    'lookout': '~/SynologyDrive/Work/CT/Web/lookout',
    'keel': '~/SynologyDrive/Work/CT/Web/keel',
    'admiralty': '~/SynologyDrive/Work/CT/Web/beacon',
    'manifest': '~/SynologyDrive/Work/CT/Web/harbor',
}


class ChangeRequest(models.Model):
    """A user-submitted change request for a DockLabs product."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Who submitted and from which product
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='change_requests',
    )
    submitted_by_name = models.CharField(
        max_length=255, blank=True,
        help_text=_('Captured at submission time in case user is deleted.'),
    )
    submitted_by_email = models.EmailField(blank=True)
    product = models.CharField(max_length=50)

    # Request details
    title = models.CharField(max_length=255)
    description = models.TextField(
        help_text=_('Describe what you want changed, added, or fixed.'),
    )
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.FEATURE,
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.MEDIUM,
    )

    # Optional: page URL or screenshot reference
    page_url = models.CharField(
        max_length=500, blank=True,
        help_text=_('The page this relates to (if applicable).'),
    )

    # Admin review
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    admin_notes = models.TextField(
        blank=True,
        help_text=_('Scope, constraints, or implementation guidance.'),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True)

    # Implementation tracking
    implemented_at = models.DateTimeField(null=True, blank=True)
    implementation_notes = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'keel_change_request'
        ordering = ['-created_at']
        verbose_name = _('change request')
        verbose_name_plural = _('change requests')

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title}"

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------
    def approve(self, reviewer, notes=''):
        """Approve this request for implementation."""
        self.status = Status.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        if notes:
            self.admin_notes = notes
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'admin_notes', 'updated_at',
        ])

    def decline(self, reviewer, reason=''):
        """Decline this request."""
        self.status = Status.DECLINED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.decline_reason = reason
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'decline_reason', 'updated_at',
        ])

    def mark_implementing(self):
        """Mark as currently being implemented."""
        self.status = Status.IMPLEMENTING
        self.save(update_fields=['status', 'updated_at'])

    def mark_implemented(self, notes=''):
        """Mark as implemented."""
        self.status = Status.IMPLEMENTED
        self.implemented_at = timezone.now()
        if notes:
            self.implementation_notes = notes
        self.save(update_fields=[
            'status', 'implemented_at', 'implementation_notes', 'updated_at',
        ])

    # ------------------------------------------------------------------
    # Claude Code prompt generation
    # ------------------------------------------------------------------
    def generate_prompt(self):
        """Generate a Claude Code prompt for implementing this request.

        Returns a ready-to-paste prompt string scoped to the correct
        product directory with full context.
        """
        product_path = PRODUCT_PATHS.get(self.product.lower(), '')
        category_label = self.get_category_display()
        priority_label = self.get_priority_display()

        sections = []

        # Header
        sections.append(f"# Change Request: {self.title}")
        sections.append(f"**Product:** {self.product.title()}")
        sections.append(f"**Category:** {category_label}")
        sections.append(f"**Priority:** {priority_label}")
        sections.append(f"**Submitted by:** {self.submitted_by_name or 'Unknown'}")
        if self.page_url:
            sections.append(f"**Related page:** {self.page_url}")

        # User's description
        sections.append(f"\n## User Request\n\n{self.description}")

        # Admin guidance
        if self.admin_notes:
            sections.append(f"\n## Implementation Guidance\n\n{self.admin_notes}")

        # Instructions
        sections.append(dedent(f"""
## Instructions

1. Read the relevant code in the {self.product.title()} product to understand the current state
2. Implement the change described above, following the admin guidance if provided
3. Use the shared Keel design system (docklabs.css variables, Bootstrap 5 components)
4. Ensure the change is consistent with other DockLabs products
5. Run tests to verify nothing is broken
6. Commit with a descriptive message referencing this change request
""").strip())

        if product_path:
            sections.append(f"\n**Working directory:** `{product_path}`")

        return '\n\n'.join(sections)
