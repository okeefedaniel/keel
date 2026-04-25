"""
Keel shared models — abstract base classes for DockLabs products.

Products inherit from these and add domain-specific fields/methods.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# Agency (state agencies / partner organizations)
# ---------------------------------------------------------------------------
class AbstractAgency(models.Model):
    """Base agency model. Subclass in each product to add domain fields."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    abbreviation = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)

    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)

    is_active = models.BooleanField(default=True)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['abbreviation']

    def __str__(self):
        return f"{self.abbreviation} - {self.name}"


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------
class AbstractAuditLog(models.Model):
    """Immutable log of user actions for compliance and auditing.

    Records cannot be modified or deleted through the Django ORM.
    This ensures audit trail integrity for FOIA and compliance.

    Subclass and extend Action choices per product:

        class Action(AbstractAuditLog.Action):
            FOIA_SEARCH = 'foia_search', 'FOIA Search'
    """

    class Action(models.TextChoices):
        CREATE = 'create', _('Create')
        UPDATE = 'update', _('Update')
        DELETE = 'delete', _('Delete')
        STATUS_CHANGE = 'status_change', _('Status Change')
        SUBMIT = 'submit', _('Submit')
        APPROVE = 'approve', _('Approve')
        REJECT = 'reject', _('Reject')
        LOGIN = 'login', _('Login')
        EXPORT = 'export', _('Export')
        VIEW = 'view', _('View')
        LOGIN_FAILED = 'login_failed', _('Login Failed')
        SECURITY_EVENT = 'security_event', _('Security Event')
        ARCHIVE = 'archive', _('Archive')
        UNARCHIVE = 'unarchive', _('Unarchive')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_audit_logs',
    )
    action = models.CharField(max_length=25, choices=Action.choices)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        # Audit logs are append-only: prevent updates to existing records
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError(
                'Audit log records are immutable and cannot be modified. '
                'Create a new record instead.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Prevent deletion of audit records
        raise ValueError(
            'Audit log records cannot be deleted. '
            'They are retained for compliance and legal requirements.'
        )

    def __str__(self):
        user_display = self.user if self.user else 'System'
        return f"{user_display} - {self.get_action_display()} - {self.entity_type} ({self.timestamp:%Y-%m-%d %H:%M})"


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------
class AbstractNotification(models.Model):
    """In-app notification delivered to a user."""

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')
        URGENT = 'urgent', _('Urgent')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(app_label)s_notifications',
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} -> {self.recipient}"


# ---------------------------------------------------------------------------
# ArchivedRecord
# ---------------------------------------------------------------------------
class AbstractArchivedRecord(models.Model):
    """Tracks archived records for data retention compliance.

    Subclass and override EntityType and RetentionPolicy per product.
    """

    class RetentionPolicy(models.TextChoices):
        STANDARD = 'standard', _('Standard (7 years)')
        EXTENDED = 'extended', _('Extended (10 years)')
        PERMANENT = 'permanent', _('Permanent')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=20)
    entity_id = models.CharField(max_length=255)
    entity_description = models.TextField(blank=True)
    retention_policy = models.CharField(
        max_length=15, choices=RetentionPolicy.choices, default=RetentionPolicy.STANDARD,
    )
    original_created_at = models.DateTimeField()
    archived_at = models.DateTimeField(auto_now_add=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    retention_expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_purged = models.BooleanField(default=False)
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ['-archived_at']

    def __str__(self):
        return f"Archived {self.entity_type} - {self.entity_id}"


# ---------------------------------------------------------------------------
# StatusHistory — immutable workflow transition audit trail
# ---------------------------------------------------------------------------
class AbstractStatusHistory(models.Model):
    """Immutable record of a workflow status transition.

    Products subclass and add a ForeignKey to their domain model:

        class ApplicationStatusHistory(AbstractStatusHistory):
            application = models.ForeignKey(Application, ...)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    old_status = models.CharField(max_length=50)
    new_status = models.CharField(max_length=50)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_%(class)s_changes',
    )
    comment = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.old_status} → {self.new_status} ({self.changed_at:%Y-%m-%d %H:%M})"


# ---------------------------------------------------------------------------
# InternalNote — staff comments with visibility control
# ---------------------------------------------------------------------------
class AbstractInternalNote(models.Model):
    """Internal staff note/comment on a record.

    Products subclass and add a ForeignKey to their domain model:

        class ApplicationComment(AbstractInternalNote):
            application = models.ForeignKey(Application, ...)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_%(class)s_authored',
    )
    content = models.TextField()
    is_internal = models.BooleanField(
        default=True,
        help_text=_('If True, only visible to staff. If False, visible to external users.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def __str__(self):
        author_name = self.author.get_full_name() if self.author else 'System'
        return f"{author_name} ({self.created_at:%Y-%m-%d %H:%M})"


# ---------------------------------------------------------------------------
# WorkflowModelMixin — standard workflow interface for any status-based model
# ---------------------------------------------------------------------------
class WorkflowModelMixin:
    """Mixin for models managed by a WorkflowEngine.

    Products define a ``WORKFLOW`` class attribute pointing to their engine:

        from keel.core.models import WorkflowModelMixin, KeelBaseModel

        class Invitation(WorkflowModelMixin, KeelBaseModel):
            WORKFLOW = INVITATION_WORKFLOW
            status = models.CharField(max_length=50, default='received')

    This provides ``transition()``, ``get_available_transitions()``, and
    ``can_transition()`` without per-model boilerplate.
    """

    def get_available_transitions(self, user=None):
        """Return Transition objects available from the current status."""
        return self.WORKFLOW.get_available_transitions(self.status, user)

    def transition(self, target_status, user=None, comment=''):
        """Execute a workflow transition. Validates state and roles."""
        return self.WORKFLOW.execute(self, target_status, user=user, comment=comment)

    def can_transition(self, target_status, user=None):
        """Check if a transition to target_status is allowed."""
        return self.WORKFLOW.can_transition(self.status, target_status, user)


# ---------------------------------------------------------------------------
# KeelBaseModel — standard abstract base for all new Keel and product models
# ---------------------------------------------------------------------------
class KeelBaseModel(models.Model):
    """Standard abstract base providing UUID PK, timestamps, and created_by.

    All new Keel module models and product-specific models should inherit
    from this to ensure consistent field patterns across the DockLabs suite.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(app_label)s_%(class)s_created',
    )

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Project Lifecycle abstracts
#
# These three abstracts back the suite-wide "project lifecycle" pattern
# documented in keel/CLAUDE.md (Project Lifecycle Standard): something
# enters a product, gets CLAIMED by a principal driver, accumulates
# COLLABORATORS, gathers diligence in the form of notes
# (AbstractInternalNote) and ATTACHMENTS, progresses through stages via
# WorkflowEngine, and — if signature is required — hands off to Manifest
# via keel.signatures.client.send_to_manifest.
#
# Products subclass these abstracts and add the ForeignKey to the owning
# domain model (Opportunity, TrackedBill, Application, etc.).
# ---------------------------------------------------------------------------


class AbstractAssignment(models.Model):
    """Claim / assignment of a project-lifecycle object to a principal driver.

    Captures the explicit "claim" gesture — distinct from record creation —
    so a product can maintain an unowned pool of work that users or managers
    pull from. Modeled on Harbor's ``ApplicationAssignment``.

    Products subclass and add a ForeignKey to the owning entity:

        class OpportunityAssignment(AbstractAssignment):
            opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE)

    Pairs with WorkflowModelMixin; the ``status`` field here tracks the
    assignment's own lifecycle, not the owning object's workflow.
    """

    class AssignmentType(models.TextChoices):
        CLAIMED = 'claimed', _('Self-claimed')
        MANAGER_ASSIGNED = 'manager_assigned', _('Manager-assigned')

    class Status(models.TextChoices):
        ASSIGNED = 'assigned', _('Assigned')
        IN_PROGRESS = 'in_progress', _('In progress')
        COMPLETED = 'completed', _('Completed')
        REASSIGNED = 'reassigned', _('Reassigned')
        RELEASED = 'released', _('Released back to pool')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(app_label)s_%(class)s_assigned',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(app_label)s_%(class)s_delegated',
        help_text=_('Manager who made the assignment; null for self-claims.'),
    )
    assignment_type = models.CharField(
        max_length=20, choices=AssignmentType.choices,
        default=AssignmentType.CLAIMED,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ASSIGNED,
    )
    claimed_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ['-claimed_at']

    def __str__(self):
        who = self.assigned_to.get_full_name() if self.assigned_to else 'unassigned'
        return f"{self.get_assignment_type_display()} — {who} ({self.get_status_display()})"


class AbstractCollaborator(models.Model):
    """A person (internal user OR external email invite) collaborating on a
    project-lifecycle object.

    Canonical role vocabulary across the suite. Supports both internal users
    (``user`` FK set) and external invites (``user`` null, ``email``/``name``
    set). Tracks the full invite lifecycle.

    Products subclass and add a ForeignKey to the owning entity:

        class OpportunityCollaborator(AbstractCollaborator):
            opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE)

            class Meta(AbstractCollaborator.Meta):
                unique_together = [('opportunity', 'user'), ('opportunity', 'email')]
    """

    class Role(models.TextChoices):
        LEAD = 'lead', _('Lead')
        CONTRIBUTOR = 'contributor', _('Contributor')
        REVIEWER = 'reviewer', _('Reviewer')
        OBSERVER = 'observer', _('Observer')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='%(app_label)s_%(class)s_memberships',
        help_text=_('Internal user; null for external email invites.'),
    )
    email = models.EmailField(blank=True, help_text=_('Set for external invites.'))
    name = models.CharField(max_length=255, blank=True)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.CONTRIBUTOR,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(app_label)s_%(class)s_invited',
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notify_on_notes = models.BooleanField(default=True)
    notify_on_status = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ['-invited_at']

    def __str__(self):
        who = (
            self.user.get_full_name() if self.user
            else (self.name or self.email or 'unknown')
        )
        return f"{who} ({self.get_role_display()})"

    @property
    def is_external(self):
        """True when this is an email-only invite (no internal user linked)."""
        return self.user_id is None

    @property
    def is_pending(self):
        """True when the invite has not yet been accepted."""
        return self.accepted_at is None


class AbstractAttachment(models.Model):
    """A document or file attached to a project-lifecycle object.

    Provides the same applicant-visible / staff-only visibility split that
    Harbor's ``ApplicationDocument`` / ``StaffDocument`` pair established,
    unified in a single abstract via the ``visibility`` field. Also the
    destination for signed PDFs returned from the Manifest roundtrip.

    Products subclass and add a ForeignKey to the owning entity:

        class OpportunityAttachment(AbstractAttachment):
            opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE)

    File storage uses the product's configured default storage. Products
    that need FOIA export must register their concrete attachment subclass
    with ``keel.foia.export``.
    """

    class Visibility(models.TextChoices):
        EXTERNAL = 'external', _('External (applicant-visible)')
        INTERNAL = 'internal', _('Internal (staff-only)')

    class Source(models.TextChoices):
        UPLOAD = 'upload', _('Manually uploaded')
        MANIFEST_SIGNED = 'manifest_signed', _('Signed document returned from Manifest')
        SYSTEM = 'system', _('System-generated')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to='attachments/%Y/%m/')
    filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    description = models.TextField(blank=True)
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.INTERNAL,
    )
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.UPLOAD,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(app_label)s_%(class)s_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # String back-pointer to a Manifest packet when source==MANIFEST_SIGNED.
    # No cross-DB FK — products and Manifest may run on separate databases.
    manifest_packet_uuid = models.CharField(max_length=64, blank=True)

    class Meta:
        abstract = True
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.filename or (self.file.name if self.file else f'Attachment {self.id}')

    def save(self, *args, **kwargs):
        # Auto-populate filename and size_bytes from the uploaded file when
        # not explicitly provided, so product views don't have to repeat this.
        if self.file and not self.filename:
            self.filename = self.file.name.rsplit('/', 1)[-1]
        if self.file and not self.size_bytes:
            try:
                self.size_bytes = self.file.size
            except (OSError, ValueError):
                pass
        super().save(*args, **kwargs)
