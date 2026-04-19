"""Keel accounts — centralized user identity and product access.

Products set AUTH_USER_MODEL = 'keel_accounts.KeelUser' and use the
ProductAccess model to control which products a user can reach and
what role they hold in each.

Invitations let admins invite users to products via email link.
"""
import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# Products registry — products declare themselves in settings
# ---------------------------------------------------------------------------
class Product(models.TextChoices):
    """Known DockLabs products.

    Extend via KEEL_EXTRA_PRODUCTS in settings:
        KEEL_EXTRA_PRODUCTS = [('my_app', 'My App')]
    """
    BEACON = 'beacon', _('Beacon CRM')
    ADMIRALTY = 'admiralty', _('Admiralty FOIA')
    HARBOR = 'harbor', _('Harbor Grants')
    MANIFEST = 'manifest', _('Manifest Signing')
    LOOKOUT = 'lookout', _('Lookout Legislative')
    BOUNTY = 'bounty', _('Bounty Federal Grants')
    PURSER = 'purser', _('Purser Finance')
    HELM = 'helm', _('Helm Executive Dashboard')
    YEOMAN = 'yeoman', _('Yeoman Scheduling')
    KEEL = 'keel', _('Keel Admin')


# ---------------------------------------------------------------------------
# Product → Role registry
# ---------------------------------------------------------------------------
PRODUCT_ROLES = {
    'beacon': [
        ('system_admin', 'System Administrator'),
        ('agency_admin', 'Agency Administrator'),
        ('relationship_manager', 'Relationship Manager'),
        ('foia_officer', 'FOIA Officer'),
        ('foia_attorney', 'FOIA Attorney'),
        ('analyst', 'Analyst'),
        ('executive', 'Executive (Read-Only)'),
        ('act_admin', 'AdvanceCT Administrator'),
        ('act_relationship_mgr', 'AdvanceCT Relationship Manager'),
        ('act_analyst', 'AdvanceCT Analyst'),
    ],
    'admiralty': [
        ('system_admin', 'System Administrator'),
        ('foia_manager', 'FOIA Manager'),
        ('foia_officer', 'FOIA Officer'),
        ('foia_attorney', 'FOIA Attorney'),
    ],
    'harbor': [
        ('system_admin', 'System Administrator'),
        ('agency_admin', 'Agency Administrator'),
        ('program_officer', 'Program Officer'),
        ('fiscal_officer', 'Fiscal Officer'),
        ('federal_fund_coordinator', 'Federal Fund Coordinator'),
        ('reviewer', 'Reviewer'),
        ('applicant', 'Applicant'),
        ('auditor', 'Auditor'),
    ],
    'manifest': [
        ('admin', 'Admin'),
        ('staff', 'Staff'),
        ('signer', 'Signer'),
    ],
    'lookout': [
        ('admin', 'Admin'),
        ('legislative_aid', 'Legislative Aid'),
        ('stakeholder', 'Stakeholder'),
    ],
    'bounty': [
        ('admin', 'Admin'),
        ('coordinator', 'Federal Fund Coordinator'),
        ('analyst', 'Analyst'),
        ('viewer', 'Viewer'),
    ],
    'purser': [
        ('purser_admin', 'Purser Admin'),
        ('purser_submitter', 'Submitter'),
        ('purser_reviewer', 'Reviewer'),
        ('purser_compliance_officer', 'Compliance Officer'),
        ('purser_readonly', 'Read-Only'),
        ('external_submitter', 'External Submitter'),
    ],
    'helm': [
        ('helm_admin', 'Admin'),
        ('helm_director', 'Director'),
        ('helm_viewer', 'Viewer'),
    ],
    'yeoman': [
        ('yeoman_admin', 'Administrator'),
        ('yeoman_scheduler', 'Scheduler'),
        ('yeoman_viewer', 'Viewer'),
        ('yeoman_delegate', 'Delegate'),
    ],
    'keel': [
        ('admin', 'Admin'),
        ('system_admin', 'System Administrator'),
    ],
}


def get_product_choices():
    """Return product choices including any extras from settings."""
    choices = list(Product.choices)
    extras = getattr(settings, 'KEEL_EXTRA_PRODUCTS', [])
    choices.extend(extras)
    return choices


def get_product_roles(product=None):
    """Return role choices for a product, or all roles keyed by product.

    If product is None, returns the full PRODUCT_ROLES dict.
    If product is 'all', returns a merged list of common roles.
    """
    extras = getattr(settings, 'KEEL_EXTRA_PRODUCT_ROLES', {})
    all_roles = {**PRODUCT_ROLES, **extras}

    if product is None:
        return all_roles
    if product == 'all':
        # For suite-wide invitations, offer roles common across products
        return [
            ('admin', 'Admin'),
            ('system_admin', 'System Administrator'),
        ]
    return all_roles.get(product, [('admin', 'Admin')])


# ---------------------------------------------------------------------------
# KeelUser — the single identity across all DockLabs products
# ---------------------------------------------------------------------------
class KeelUser(AbstractUser):
    """Centralized user identity for all DockLabs products.

    Product-specific roles live in ProductAccess, not here.
    This model holds identity and common profile fields only.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Common profile fields (shared across products)
    title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    agency = models.ForeignKey(
        'keel_accounts.Agency', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='users',
    )
    is_state_user = models.BooleanField(
        default=False,
        help_text=_('Designates whether this user belongs to a state agency.'),
    )

    # Terms acceptance
    accepted_terms = models.BooleanField(default=False)
    accepted_terms_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'keel_user'
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def __str__(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username

    # ------------------------------------------------------------------
    # Product access helpers
    # ------------------------------------------------------------------
    def has_product_access(self, product):
        """Check if user can access a specific product."""
        return self.product_access.filter(
            product=product, is_active=True,
        ).exists()

    def get_product_role(self, product):
        """Return the user's role for a specific product, or None."""
        access = self.product_access.filter(
            product=product, is_active=True,
        ).first()
        return access.role if access else None

    def get_products(self):
        """Return list of products this user can access."""
        return list(
            self.product_access
            .filter(is_active=True)
            .values_list('product', flat=True)
        )

    # Human-friendly labels for product roles. Add new roles here as
    # products define them; unknown roles get title-cased automatically.
    ROLE_LABELS = {
        'system_admin': 'System Admin',
        'admin': 'Administrator',
        'analyst': 'Analyst',
        'relationship_manager': 'Relationship Manager',
        'program_officer': 'Program Officer',
        'fiscal_officer': 'Fiscal Officer',
        'federal_coordinator': 'Federal Coordinator',
        'applicant': 'Applicant',
        'auditor': 'Auditor',
        'viewer': 'Viewer',
        'coordinator': 'Coordinator',
        'foia_officer': 'FOIA Officer',
        'foia_attorney': 'FOIA Attorney',
        'scheduler': 'Scheduler',
        'delegate': 'Delegate',
    }

    @property
    def role(self):
        """Return the role for the current product (set by middleware).

        Falls back to checking ProductAccess directly using
        KEEL_PRODUCT_NAME from settings. This keeps existing
        @role_required decorators working unchanged.
        """
        # Middleware sets _product_role on the user instance per-request
        if hasattr(self, '_product_role'):
            return self._product_role
        # Fallback: look up from settings
        product = getattr(settings, 'KEEL_PRODUCT_NAME', '').lower()
        if product:
            return self.get_product_role(product)
        return None

    def get_role_display(self):
        """Human-friendly label for the current product role.

        Returns e.g. "System Admin" instead of "system_admin". Falls
        back to title-casing the raw role string so unknown roles
        still look presentable. Returns "User" when no role is
        assigned (matches the old sidebar default).

        In ``DEMO_MODE``, the label is prefixed with "Demo" so every
        role reads "Demo System Admin", "Demo Analyst", etc. — a
        consistent visual cue that you're on a demo instance.
        """
        raw = self.role
        if not raw:
            return 'User'
        label = self.ROLE_LABELS.get(raw, raw.replace('_', ' ').title())
        if getattr(settings, 'DEMO_MODE', False):
            return f'Demo {label}'
        return label

    def accept_terms(self):
        """Record terms acceptance with timestamp."""
        self.accepted_terms = True
        self.accepted_terms_at = timezone.now()
        self.save(update_fields=['accepted_terms', 'accepted_terms_at'])


# ---------------------------------------------------------------------------
# Agency — concrete shared model (replaces AbstractAgency for shared DB)
# ---------------------------------------------------------------------------
class Agency(models.Model):
    """State agency or partner organization.

    Concrete model in the shared Keel database so agencies are
    consistent across all products.
    """

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
        db_table = 'keel_agency'
        ordering = ['abbreviation']
        verbose_name_plural = _('agencies')

    def __str__(self):
        return f"{self.abbreviation} - {self.name}"


# ---------------------------------------------------------------------------
# ProductAccess — which products a user can reach and their role in each
# ---------------------------------------------------------------------------
class ProductAccess(models.Model):
    """Links a user to a product with a product-specific role.

    One user can have access to multiple products, each with a
    different role. The role value is product-specific (e.g.,
    'program_officer' in Harbor, 'legislative_aid' in Lookout).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        KeelUser, on_delete=models.CASCADE,
        related_name='product_access',
    )
    product = models.CharField(max_length=50)
    role = models.CharField(
        max_length=50,
        help_text=_('Product-specific role (e.g., program_officer, admin).'),
    )
    is_active = models.BooleanField(default=True)
    is_beta_tester = models.BooleanField(
        default=False,
        help_text=_('Beta testers can submit feedback directly from within the product.'),
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        KeelUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        db_table = 'keel_product_access'
        unique_together = [('user', 'product')]
        verbose_name = _('product access')
        verbose_name_plural = _('product access')

    def __str__(self):
        return f"{self.user} — {self.product} ({self.role})"


# ---------------------------------------------------------------------------
# Invitation — invite users to a product via email link
# ---------------------------------------------------------------------------
def _generate_token():
    return secrets.token_urlsafe(48)


class Invitation(models.Model):
    """Email invitation to grant a user access to a product.

    Flow:
    1. Admin creates invitation with email, product, role
    2. System sends email with unique link containing the token
    3. User clicks link → creates account (or links existing) → gets ProductAccess
    4. Invitation marked as accepted
    """

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        ACCEPTED = 'accepted', _('Accepted')
        EXPIRED = 'expired', _('Expired')
        REVOKED = 'revoked', _('Revoked')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    product = models.CharField(max_length=50)
    role = models.CharField(max_length=50)
    token = models.CharField(max_length=100, unique=True, default=_generate_token)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
    )

    is_beta_tester = models.BooleanField(
        default=False,
        help_text=_('Grant beta tester status when invitation is accepted.'),
    )

    invited_by = models.ForeignKey(
        KeelUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sent_invitations',
    )
    accepted_by = models.ForeignKey(
        KeelUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accepted_invitations',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'keel_invitation'
        ordering = ['-created_at']

    def __str__(self):
        return f"Invite {self.email} → {self.product} ({self.role})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_usable(self):
        return self.status == self.Status.PENDING and not self.is_expired

    def accept(self, user):
        """Accept this invitation and grant product access."""
        if not self.is_usable:
            raise ValueError('Invitation is no longer valid.')

        access, created = ProductAccess.objects.get_or_create(
            user=user,
            product=self.product,
            defaults={
                'role': self.role,
                'is_beta_tester': self.is_beta_tester,
                'granted_by': self.invited_by,
            },
        )
        if not created:
            updated_fields = []
            if not access.is_active:
                access.is_active = True
                access.role = self.role
                updated_fields.extend(['is_active', 'role'])
            if self.is_beta_tester and not access.is_beta_tester:
                access.is_beta_tester = True
                updated_fields.append('is_beta_tester')
            if updated_fields:
                access.save(update_fields=updated_fields)

        self.status = self.Status.ACCEPTED
        self.accepted_by = user
        self.accepted_at = timezone.now()
        self.save(update_fields=['status', 'accepted_by', 'accepted_at'])
        return access

    def revoke(self):
        """Revoke a pending invitation."""
        if self.status == self.Status.PENDING:
            self.status = self.Status.REVOKED
            self.save(update_fields=['status'])


# ---------------------------------------------------------------------------
# Notification — concrete notification for the Keel admin console
# ---------------------------------------------------------------------------
class Notification(models.Model):
    """In-app notification for the Keel admin console."""

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')
        URGENT = 'urgent', _('Urgent')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        KeelUser, on_delete=models.CASCADE,
        related_name='keel_notifications',
    )
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True)
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM,
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'keel_notification'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f"{'[Read]' if self.is_read else '[New]'} {self.title}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class NotificationPreference(models.Model):
    """Per-user, per-notification-type channel preferences for Keel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        KeelUser, on_delete=models.CASCADE,
        related_name='keel_notification_preferences',
    )
    notification_type = models.CharField(max_length=100)
    channel_in_app = models.BooleanField(default=True)
    channel_email = models.BooleanField(default=True)
    channel_sms = models.BooleanField(default=False)
    channel_boswell = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'keel_notification_preference'
        unique_together = [('user', 'notification_type')]


class NotificationLog(models.Model):
    """Delivery tracking for Keel notifications."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(KeelUser, on_delete=models.CASCADE, related_name='+')
    notification_type = models.CharField(max_length=100)
    channel = models.CharField(max_length=20)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'keel_notification_log'
        ordering = ['-created_at']


# ---------------------------------------------------------------------------
# NotificationTypeOverride — admin overrides to notification routing
# ---------------------------------------------------------------------------
class NotificationTypeOverride(models.Model):
    """Admin overrides to notification type routing.

    Stores fields that differ from the hardcoded defaults in product_types.py.
    On startup, these are loaded and applied on top of the registry defaults.
    """

    key = models.CharField(
        max_length=100, unique=True, db_index=True,
        help_text=_('Notification type key (e.g., application_submitted).'),
    )
    channels = models.JSONField(
        default=list, blank=True,
        help_text=_('Override default_channels (e.g., ["in_app", "email"]).'),
    )
    roles = models.JSONField(
        default=list, blank=True,
        help_text=_('Override default_roles (e.g., ["admin", "program_officer"]).'),
    )
    priority = models.CharField(
        max_length=10, blank=True,
        help_text=_('Override priority (low, medium, high, urgent).'),
    )
    allow_mute = models.BooleanField(
        null=True,
        help_text=_('Override allow_mute. Null means use hardcoded default.'),
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        KeelUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        db_table = 'keel_notification_type_override'
        verbose_name = _('notification type override')
        verbose_name_plural = _('notification type overrides')

    def __str__(self):
        return f"Override: {self.key}"


# ---------------------------------------------------------------------------
# AuditLog — concrete audit log for the Keel admin console
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    """Concrete audit log for the Keel site.

    Products that subclass AbstractAuditLog have their own tables.
    This one aggregates platform-level events (logins, admin actions,
    change requests, etc.) and can also ingest events from products
    via the API or management commands.
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
        KeelUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='audit_logs',
    )
    action = models.CharField(max_length=25, choices=Action.choices)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    product = models.CharField(max_length=50, blank=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'keel_audit_log'
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError('Audit log records are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Audit log records cannot be deleted.')

    def __str__(self):
        user_display = self.user if self.user else 'System'
        return f"{user_display} - {self.get_action_display()} - {self.entity_type} ({self.timestamp:%Y-%m-%d %H:%M})"
