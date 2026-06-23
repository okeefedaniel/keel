"""
Keel shared models — abstract base classes for DockLabs products.

Products inherit from these and add domain-specific fields/methods.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils.translation import gettext_lazy as _

from keel.security.scanning import FileSecurityValidator


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

    **AuditLog is exclusively for user actions** (Approach D, v0.46.0). The
    schema enforces ``user IS NOT NULL`` both via Django's ``null=False`` and
    a DB-level ``CheckConstraint``. System events — cron poll summaries,
    cache refreshes, batch imports, failed logins, lockout events — flow
    through ``keel.activity.services.record_system_event()`` into the
    ``Activity`` stream instead. See
    ``~/.claude/plans/audit-activity-notifications-rethink.md`` for the
    canonical spec.

    Outside a request context (Celery tasks, ``./manage.py shell`` mutations,
    user-attributable RunPython migrations), wrap the work in
    ``keel.core.middleware.audit_context(user=...)`` to re-establish the
    thread-local so signal-based auto-audit can attribute the row. Without
    that context, the gate in ``keel/core/audit_signals.py:_on_save`` drops
    the would-be NULL-user row before it hits the schema constraint.

    Subclass and extend Action choices per product:

        class Action(AbstractAuditLog.Action):
            FOIA_SEARCH = 'foia_search', 'FOIA Search'

    The ``LOGIN_FAILED`` and ``SECURITY_EVENT`` choices were removed in
    v0.46.0 — those events route to Activity now (verbs ``auth.login_failed``,
    ``security.account_locked``, ``security.suspicious_activity``).
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
        # NOTE: LOGIN_FAILED and SECURITY_EVENT were removed in v0.46.0
        # (Approach D). Those events now write to Activity via
        # record_system_event(verb='auth.login_failed' / 'security.*'), not
        # AuditLog. Successful logins still write AuditLog (LOGIN above) —
        # the user attribution naturally satisfies the NOT NULL constraint.
        ARCHIVE = 'archive', _('Archive')
        UNARCHIVE = 'unarchive', _('Unarchive')
        ROLE_GRANT_DENIED = 'role_grant_denied', _('Role Grant Denied')
        USERNAME_CHANGE = 'username_change', _('Username Change')
        EMAIL_CHANGE = 'email_change', _('Email Change')
        AVATAR_CHANGE = 'avatar_change', _('Avatar Change')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=False, blank=False, related_name='%(app_label)s_audit_logs',
        help_text='The user who performed the action. AuditLog is user-only '
                  'under Approach D — system events go through Activity.',
    )
    action = models.CharField(max_length=25, choices=Action.choices)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    changes = models.JSONField(
        default=dict, blank=True,
        help_text='Snapshot of audited field values at save time (auto-signal pathway). '
                  'Empty for explicit log_audit() / record_activity() calls — they use '
                  'the metadata field for free-form context instead. changes retains '
                  'diff/snapshot semantics that downstream tooling depends on.',
    )
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text='Free-form context for explicit audit emission (record_activity, manual '
                  'log_audit calls with structured info). Distinct from changes which '
                  'auto-signal populates with field snapshots.',
    )
    deep_link_snapshot = models.CharField(
        max_length=256, blank=True, default='',
        help_text='Absolute URL of the audited target captured at audit-write time. Used '
                  'by keel.activity promotion rules to avoid stale URLs when backfilling '
                  'or replaying audit history through the activity layer.',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-timestamp']
        constraints = [
            # Defense-in-depth against the Django ORM accidentally creating a
            # NULL-user audit row even though null=False is declared above:
            # a DB-level check that rejects any user_id IS NULL insert.
            #
            # The name is TEMPLATED (%(app_label)s_%(class)s) so each concrete
            # subclass gets a globally-unique constraint name — e.g.
            # bounty_core_auditlog_user_required. A hardcoded name here triggers
            # Django E032 (constraint names must be unique across all models in
            # a project): the moment a consumer's concrete AuditLog inherits
            # this constraint AND keel.accounts.AuditLog also carries one,
            # makemigrations fails. Templating is what Django provides abstract
            # bases for. The canary's audit_constraint_present gauge verifies
            # the protection via column nullability, not the constraint name,
            # so per-product name variation is harmless.
            CheckConstraint(
                # ``condition=`` is the Django 5.1+ name; ``check=`` was
                # removed entirely in Django 6.0, where it raises a
                # ``TypeError`` at class-definition time and takes every
                # keel import down with it. The two kwargs are otherwise
                # interchangeable — Django stores both as ``self.condition``
                # and ``deconstruct()`` emits ``condition=`` regardless — so
                # this flip is migration-churn-free: a consumer's concrete
                # AuditLog subclass deconstructs identically and
                # ``makemigrations`` detects no change.
                condition=Q(user__isnull=False),
                name='%(app_label)s_%(class)s_user_required',
            ),
        ]

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
    # @-mentions: populated by keel.mentions.forms.MentionFormMixin on save.
    # The M2M is harmless when keel.mentions is not installed (stays empty).
    # Adopting products must run makemigrations + migrate on every concrete
    # subclass after bumping keel to 0.42.0 — see keel/mentions/README.md.
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='%(app_label)s_%(class)s_mentioned_in',
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
        """Return Transition objects available from the current status.

        Forwards ``obj=self`` to the engine so subclasses that resolve
        object-scoped roles (e.g. Helm's ``ProjectWorkflowEngine`` checking
        ``ProjectCollaborator(role=LEAD)`` against the bound project) see
        the model instance — without it, per-record role checks silently
        fall through to the base ``_user_has_role`` and ignore ``obj``.
        """
        return self.WORKFLOW.get_available_transitions(self.status, user, obj=self)

    def transition(self, target_status, user=None, comment=''):
        """Execute a workflow transition. Validates state and roles."""
        return self.WORKFLOW.execute(self, target_status, user=user, comment=comment)

    def can_transition(self, target_status, user=None):
        """Check if a transition to target_status is allowed.

        Forwards ``obj=self`` to the engine so object-scoped role checks
        receive the model instance. See ``get_available_transitions`` above.
        """
        return self.WORKFLOW.can_transition(self.status, target_status, user, obj=self)


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
    file = models.FileField(
        upload_to='attachments/%Y/%m/',
        validators=[FileSecurityValidator()],
    )
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


# ---------------------------------------------------------------------------
# Tags and Groups — suite-wide primitives for classifying entity records.
#
# Tag  = admin-curated categorical label (industry, region, program). Often
#        enumerated via a product-specific TagType. Cheap to apply; searchable.
# Group = user-curated cohort of records ("Reporters", "Inbound", "Board
#        Candidates"). Independent of any organizational FK; a record can
#        belong to any number of groups. Supports `is_system` for platform-
#        managed groups users cannot rename or delete.
#
# Subclasses add the owning-entity M2M plus product-specific fields (e.g.
# Beacon's `Tag.tag_type` enum, Yeoman's per-agency scoping) and any uniqueness
# constraints (global vs. per-tenant). See keel CLAUDE.md "Groups & Tags on
# People/Entity Records" for the design contract.
# ---------------------------------------------------------------------------
class AbstractTag(models.Model):
    """Categorical label applied to records for filtering and search."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=20, blank=True,
        help_text=_('Optional hex code or named color.'),
    )
    is_system = models.BooleanField(
        default=False,
        help_text=_('System-managed tags cannot be renamed or deleted by users.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['name']

    def __str__(self):
        return self.name


class AbstractGroup(models.Model):
    """User-curated cohort of records, independent of organizational parent.

    A record can belong to any number of groups. Groups do NOT imply an org
    or parent affiliation — that is the job of a product-specific FK
    (e.g. Beacon's `Contact.company`). System groups (`is_system=True`) are
    created by intake code and should not be renamed or deleted by users.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=20, blank=True,
        help_text=_('Optional hex code or named color.'),
    )
    is_system = models.BooleanField(
        default=False,
        help_text=_('System-managed groups cannot be renamed or deleted by users.'),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['name']

    def __str__(self):
        return self.name
