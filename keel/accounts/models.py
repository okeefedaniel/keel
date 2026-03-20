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
    BEACON = 'beacon', _('Beacon')
    HARBOR = 'harbor', _('Harbor')
    LOOKOUT = 'lookout', _('Lookout')


def get_product_choices():
    """Return product choices including any extras from settings."""
    choices = list(Product.choices)
    extras = getattr(settings, 'KEEL_EXTRA_PRODUCTS', [])
    choices.extend(extras)
    return choices


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
                'granted_by': self.invited_by,
            },
        )
        if not created and not access.is_active:
            access.is_active = True
            access.role = self.role
            access.save(update_fields=['is_active', 'role'])

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
