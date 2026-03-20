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
