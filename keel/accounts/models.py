"""Keel accounts — centralized user identity and product access.

Products set AUTH_USER_MODEL = 'keel_accounts.KeelUser' and use the
ProductAccess model to control which products a user can reach and
what role they hold in each.

Invitations let admins invite users to products via email link.

Organizations are the customer entity that buys DockLabs (a state
agency, vendor, internal team). Each org has a set of subscriptions
to specific products; users belong to exactly one org. Subscription
gating happens at invite time and at OIDC claim issuance — products
themselves remain ignorant of org-level subscriptions and continue
to read per-user ``ProductAccess``. Organization is orthogonal to
``Agency`` (the FOIA-side concept): one org may *represent* an agency
via the optional ``Organization.agency`` FK, but ``user.agency`` is
the user's primary agency affiliation and remains the source of truth
for the ``agency_abbr`` JWT claim.
"""
import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError

from .storage import avatar_storage
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# Slugs reserved for system-managed organizations. The default org
# created by the data migration cannot be created (or duplicated) by
# admins. Any future system-managed slug should be added here.
RESERVED_ORG_SLUGS = frozenset({'docklabs-internal'})


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
        ('agency_admin', 'Agency Administrator'),
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
        ('agency_admin', 'Agency Administrator'),
        ('staff', 'Staff'),
        ('signer', 'Signer'),
    ],
    'lookout': [
        ('admin', 'Admin'),
        ('agency_admin', 'Agency Administrator'),
        ('legislative_aid', 'Legislative Aid'),
        ('stakeholder', 'Stakeholder'),
    ],
    'bounty': [
        ('admin', 'Admin'),
        ('agency_admin', 'Agency Administrator'),
        ('coordinator', 'Federal Fund Coordinator'),
        ('analyst', 'Analyst'),
        ('viewer', 'Viewer'),
    ],
    'purser': [
        ('purser_admin', 'Purser Admin'),
        ('agency_admin', 'Agency Administrator'),
        ('purser_submitter', 'Submitter'),
        ('purser_reviewer', 'Reviewer'),
        ('purser_compliance_officer', 'Compliance Officer'),
        ('purser_readonly', 'Read-Only'),
        ('external_submitter', 'External Submitter'),
    ],
    'helm': [
        ('helm_admin', 'Admin'),
        ('agency_admin', 'Agency Administrator'),
        ('helm_director', 'Director'),
        ('helm_viewer', 'Viewer'),
    ],
    'yeoman': [
        ('yeoman_admin', 'Administrator'),
        ('agency_admin', 'Agency Administrator'),
        ('yeoman_scheduler', 'Scheduler'),
        ('yeoman_viewer', 'Viewer'),
        ('yeoman_delegate', 'Delegate'),
        ('yeoman_principal', 'Principal'),
    ],
    'keel': [
        ('system_admin', 'System Administrator'),
        ('agency_admin', 'Agency Administrator'),
        ('admin', 'Admin'),
    ],
}


def get_product_choices():
    """Return product choices including any extras from settings."""
    choices = list(Product.choices)
    extras = getattr(settings, 'KEEL_EXTRA_PRODUCTS', [])
    choices.extend(extras)
    return choices


# ---------------------------------------------------------------------------
# Organization — the customer entity that buys DockLabs
# ---------------------------------------------------------------------------
class Organization(models.Model):
    """A DockLabs customer (state agency, vendor, internal team).

    Each org has a set of ``OrganizationProductSubscription`` rows
    listing which DockLabs products it has bought. Users belong to
    exactly one org via ``KeelUser.organization``; superusers
    (cross-org admins like ``dokadmin``) leave it null.

    Subscription gating is enforced at invite time and at OIDC claim
    issuance only — products do not call back to Keel to check
    subscription state. This keeps products standalone-deployable.

    The optional ``agency`` FK lets an org be associated with a CT
    government agency (e.g. DECD-the-org represents DECD-the-agency).
    Unrelated to ``KeelUser.agency``: the user FK remains the source
    of truth for the ``agency_abbr`` JWT claim and per-user FOIA
    scoping. Org and user agency may differ for contractors.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(
        unique=True, max_length=63,
        help_text=_(
            'Stable identifier used in JWT claims and URLs. '
            'Lowercase letters, digits, hyphens only.'
        ),
    )
    name = models.CharField(max_length=255)
    agency = models.ForeignKey(
        'keel_accounts.Agency', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='organizations',
        help_text=_(
            'Optional link to the FOIA agency this org represents. '
            'Independent of KeelUser.agency.'
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'keel_organization'
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        # Reserved slugs cannot be created via admin/forms after the
        # initial migration seeds them. ``_state.adding`` is True only
        # on insert (new row) and False on update — so admins can
        # still rename or deactivate the seeded default org via admin.
        # The data migration uses ``apps.get_model`` which returns a
        # historical model without this hook, so the seed itself is
        # not blocked.
        if self.slug in RESERVED_ORG_SLUGS and self._state.adding:
            raise ValidationError({
                'slug': _(
                    f"Slug '{self.slug}' is reserved for system use."
                ),
            })

    def save(self, *args, **kwargs):
        # Run validation on save so direct ORM writes (not just admin
        # forms) hit the reserved-slug guard. Cheap on a small model.
        self.full_clean(validate_unique=False)
        super().save(*args, **kwargs)

    def active_subscription_codes(self):
        """Return the list of product codes this org actively subscribes to."""
        return OrganizationProductSubscription.active_product_codes(self)


class OrganizationProductSubscription(models.Model):
    """Which DockLabs products this org has bought access to.

    The set of active rows determines which products the org's
    members can be invited to and which `product_access` claims a
    user from this org can carry in their JWT. Mutating this table
    does NOT immediately revoke existing ``ProductAccess`` rows —
    that's the job of ``reconcile_user_product_access`` (in
    ``keel.accounts.services``).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='subscriptions',
    )
    product = models.CharField(
        max_length=50,
        choices=Product.choices,
        help_text=_('Product code (e.g. harbor, beacon).'),
    )
    is_active = models.BooleanField(default=True)
    started_at = models.DateField(default=timezone.now)
    ends_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'keel_org_product_subscription'
        unique_together = [('organization', 'product')]
        ordering = ['organization', 'product']

    def __str__(self):
        return f'{self.organization} → {self.product}'

    def clean(self):
        super().clean()
        valid_codes = {code for code, _label in get_product_choices()}
        if self.product not in valid_codes:
            raise ValidationError({
                'product': _(
                    f"'{self.product}' is not a known product code. "
                    f"Add it to KEEL_EXTRA_PRODUCTS if it's a new app."
                ),
            })

    @classmethod
    def active_product_codes(cls, organization):
        """Return product codes this org actively subscribes to.

        Accepts either an ``Organization`` instance or its primary key
        (uuid / pk). Passing the pk avoids triggering an FK fetch on
        an attached ``KeelUser`` instance, which can raise
        ``Organization.DoesNotExist`` during transactional test
        windows or partially-migrated CI databases.

        One source of truth used by the invitation matrix render path,
        the invitation POST validator, and the accept-time
        re-validation in ``Invitation.accept``. Pin lookups here so
        future caching/optimization happens in one place.
        """
        if organization is None:
            return []
        return list(
            cls.objects.filter(organization=organization, is_active=True)
                .values_list('product', flat=True)
        )


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
    timezone = models.CharField(max_length=64, blank=True)
    locale = models.CharField(max_length=10, blank=True)
    # Uploaded avatar — used on Keel itself and in standalone product
    # deployments where the user owns the local row. Storage backend
    # is selected at access time (S3 vs local FS) by ``avatar_storage()``;
    # see ``keel.accounts.storage`` for the rules.
    avatar = models.ImageField(
        upload_to='avatars/',
        null=True, blank=True,
        storage=avatar_storage,
        # Default Django ImageField max_length is 100, but our content-
        # addressed key shape ``avatars/{user_uuid}/{sha256_hex}.webp``
        # is 114 chars (8 + 36 + 1 + 64 + 5). 200 leaves headroom.
        max_length=200,
    )
    # Mirrored avatar URL from the JWT ``picture`` claim — populated on
    # OIDC sign-in for suite-mode products that don't own the upload.
    # When both ``avatar`` and ``avatar_url`` are set, ``avatar`` wins.
    avatar_url = models.URLField(blank=True, max_length=500)
    agency = models.ForeignKey(
        'keel_accounts.Agency', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='users',
    )
    is_state_user = models.BooleanField(
        default=False,
        help_text=_('Designates whether this user belongs to a state agency.'),
    )

    # The DockLabs customer entity this user belongs to. Nullable
    # so cross-org superusers (dokadmin) can span all customers.
    # The model-level invariant (in ``clean()``) enforces that any
    # non-superuser must have an organization. The data migration
    # backfills every existing user to a sentinel "DockLabs Internal"
    # org so the rollout is invisible.
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT,
        null=True, blank=True, related_name='users',
        help_text=_(
            'DockLabs customer org this user belongs to. Required '
            'for non-superusers; null only for cross-org admins.'
        ),
    )

    # Terms acceptance
    accepted_terms = models.BooleanField(default=False)
    accepted_terms_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Suite-wide logout epoch. Stamped by Keel's /suite/logout/ endpoint
    # AND by reconcile_user_product_access when an org reassignment
    # revokes ProductAccess rows. Reusing this column means existing
    # SessionFreshnessMiddleware infrastructure (deployed across all
    # 9 products in keel >= 0.20.0) automatically invalidates stale
    # cross-product sessions on org change — no new column or
    # middleware extension needed.
    last_logout_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'keel_user'
        verbose_name = _('user')
        verbose_name_plural = _('users')
        constraints = [
            # Non-superusers must have an organization. Superusers
            # (dokadmin) may span all orgs and therefore have null.
            # Defense-in-depth at the DB level, in addition to the
            # clean() invariant below.
            #
            # Uses ``condition=`` (Django 5.1+) rather than the
            # deprecated ``check=`` arg.
            models.CheckConstraint(
                condition=(
                    models.Q(organization__isnull=False)
                    | models.Q(is_superuser=True)
                ),
                name='keeluser_org_or_superuser',
            ),
        ]
        indexes = [
            # Functional index on Lower(email) so the suite's
            # ``email__iexact`` lookups (invitation existing-user check,
            # accept-time duplicate guard, allauth socialaccount linkage,
            # etc.) can use an index instead of a sequential scan.
            # Postgres planner will use this whenever it sees
            # ``LOWER(email) = ?``, which is what ``__iexact`` compiles to.
            models.Index(
                Lower('email'), name='keeluser_email_lower_idx',
            ),
        ]

    def __str__(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username

    def __init__(self, *args, **kwargs):
        # Snapshot organization_id at instance load so save() can
        # detect a change and trigger ProductAccess reconciliation.
        super().__init__(*args, **kwargs)
        self._original_organization_id = self.organization_id

    def clean(self):
        super().clean()
        # Mirror of the DB CheckConstraint as a model-level invariant
        # so admin forms surface a friendly error instead of relying
        # on the IntegrityError to bubble up.
        if not self.is_superuser and self.organization_id is None:
            raise ValidationError({
                'organization': _(
                    'Non-superuser accounts must belong to an organization. '
                    'Set is_superuser=True for cross-org admins.'
                ),
            })

    def save(self, *args, **kwargs):
        # Auto-assign the seeded "docklabs-internal" org to non-superuser
        # accounts that arrive without an organization set. Mirrors the
        # behavior of the 0011_seed_default_org data migration (which
        # backfilled every existing user) and keeps the
        # ``keeluser_org_or_superuser`` CheckConstraint satisfied for:
        #
        #   - Test fixtures that create users via ``User.objects.create()``
        #     without specifying organization (every product's test suite)
        #   - First-time OIDC sign-ins where the adapter hasn't yet wired
        #     ``user.organization`` from the JWT's ``organization`` claim
        #   - Management commands / data scripts that don't know about the
        #     new column
        #
        # Production code that DOES specify an organization (admin form,
        # invitation accept, future SSO adapter wiring) is unaffected —
        # the auto-default only fires when ``organization`` is genuinely
        # unset. A log line surfaces the case so silent fallthroughs are
        # observable.
        if (
            self.organization_id is None
            and not self.is_superuser
        ):
            try:
                from keel.accounts.models import Organization  # self-import OK
                default_org = Organization.objects.filter(
                    slug='docklabs-internal',
                ).only('id').first()
                if default_org is not None:
                    self.organization_id = default_org.id
                    import logging
                    logging.getLogger(__name__).info(
                        'KeelUser %s saved without organization; '
                        'auto-assigned to docklabs-internal',
                        self.username or self.email,
                    )
            except Exception:
                # Migration may not have run yet (initial setup); let
                # the CheckConstraint surface the real failure with a
                # clean traceback rather than swallow it here.
                pass

        # Detect org change and queue a reconcile after commit. The
        # reconcile deactivates ProductAccess rows for products the
        # new org isn't subscribed to, and bumps last_logout_at to
        # invalidate stale per-product sessions via
        # SessionFreshnessMiddleware.
        org_changed = (
            self.pk is not None
            and getattr(self, '_original_organization_id', None) != self.organization_id
        )
        super().save(*args, **kwargs)
        if org_changed:
            # Imported lazily to avoid model-import-time circular.
            from keel.accounts.services import reconcile_user_product_access
            reconcile_user_product_access(self, force_logout=True)
        # Refresh the snapshot so a later save() in the same instance
        # lifecycle doesn't double-fire.
        self._original_organization_id = self.organization_id

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
        'agency_admin': 'Agency Admin',
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
    # Bundled fix from the eng review (D3): pin choices=get_product_choices()
    # so typos like 'harbo' fail at form-clean time. choices is advisory
    # in Django (no migration needed for the column shape) — adding it
    # closes the typo class for both ProductAccess and the new
    # OrganizationProductSubscription.
    product = models.CharField(max_length=50, choices=Product.choices)
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

    batch_id = models.UUIDField(
        null=True, blank=True, db_index=True,
        help_text=_(
            'Groups invitations created in the same admin submission so that '
            'accepting any token in the batch accepts all of them.'
        ),
    )

    invited_by = models.ForeignKey(
        KeelUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sent_invitations',
    )
    accepted_by = models.ForeignKey(
        KeelUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accepted_invitations',
    )

    # The org granting access. Populated server-side from the
    # inviter's organization (or the dokadmin session-selected org
    # for cross-org admins). Nullable so the data migration can
    # backfill pending pre-rollout invitations to the default org
    # without breaking acceptance.
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT,
        null=True, blank=True, related_name='invitations',
        help_text=_('DockLabs customer org that granted this invitation.'),
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
        """Accept this invitation and grant product access.

        Performs accept-time subscription re-validation (CSO failure
        mode #4): if the inviter's org no longer subscribes to this
        invitation's product, the invitation is marked EXPIRED and
        no ProductAccess row is created. Closes the stale-sub gap
        between create-time and accept-time.
        """
        if not self.is_usable:
            raise ValueError('Invitation is no longer valid.')

        # Accept-time subscription re-validation. Only enforced when
        # the invitation carries an organization (post-rollout
        # invitations always do; the data migration backfills
        # pending pre-rollout invites to the default org).
        if self.organization_id is not None:
            subscribed = OrganizationProductSubscription.active_product_codes(
                self.organization
            )
            if self.product not in subscribed:
                self.status = self.Status.EXPIRED
                self.save(update_fields=['status'])
                raise ValueError(
                    f'Your organization is no longer subscribed to '
                    f'{self.product}. Contact your admin.'
                )

        # Assign user.organization from the invitation if the user
        # doesn't already belong to an org. This is the new-user
        # path: dokadmin invites a fresh email, the user signs up
        # via the email link, and lands in the inviter's org.
        # Existing users keep whatever org they already have (cross-
        # org users are punted to a future M2M shape per the plan).
        if (
            self.organization_id is not None
            and user.organization_id is None
            and not user.is_superuser
        ):
            user.organization_id = self.organization_id
            user.save(update_fields=['organization'])

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
# PendingEmailChange — token-bound email update awaiting verification
# ---------------------------------------------------------------------------
class PendingEmailChange(models.Model):
    """A user-initiated email change awaiting click-through confirmation.

    Used on Keel itself (where allauth is not installed) and as the
    canonical fallback path on standalone products that don't ship
    allauth either. Products that DO have allauth route through
    ``allauth.account.models.EmailAddress.add_email`` instead — see
    ``keel.accounts.services.request_email_change`` for dispatch.

    A single user may have multiple pending rows in flight (e.g. they
    asked, didn't click, then asked again). The newest unexpired row
    wins; older ones expire naturally and get pruned by the daily
    ``cleanup_expired_email_changes`` management command.
    """

    DEFAULT_TTL_HOURS = 24

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'keel_accounts.KeelUser', on_delete=models.CASCADE,
        related_name='pending_email_changes',
    )
    new_email = models.EmailField()
    # 64+ chars of urlsafe base64 = 48 bytes of entropy. Indexed because
    # the confirmation view's only lookup is by token.
    token = models.CharField(max_length=128, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'keel_pending_email_change'
        verbose_name = _('pending email change')
        verbose_name_plural = _('pending email changes')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user_id} → {self.new_email} (expires {self.expires_at:%Y-%m-%d})'

    def is_expired(self) -> bool:
        from django.utils import timezone as _tz
        return _tz.now() >= self.expires_at

    def is_consumed(self) -> bool:
        return self.confirmed_at is not None

    @classmethod
    def issue(cls, user, new_email: str, *, ttl_hours: int | None = None):
        """Create a fresh row with a urlsafe token + TTL.

        Does NOT send the email — the calling service handles that
        so the email backend choice can be deployment-specific.
        """
        from datetime import timedelta
        from django.utils import timezone as _tz
        ttl = ttl_hours if ttl_hours is not None else cls.DEFAULT_TTL_HOURS
        return cls.objects.create(
            user=user,
            new_email=new_email,
            token=secrets.token_urlsafe(48),
            expires_at=_tz.now() + timedelta(hours=ttl),
        )


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
        ROLE_GRANT_DENIED = 'role_grant_denied', _('Role Grant Denied')

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
