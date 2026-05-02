"""Data migration: seed default org, backfill users + subscriptions.

Idempotent. Safe to re-run. Designed to survive the
``run_startup() -> manage.py migrate`` boot path on every keel deploy
(including healthcheck-bounded restarts that may interrupt mid-stream).

Outputs:
  1. ``Organization(slug='docklabs-internal', name='DockLabs Internal')``
  2. 10 ``OrganizationProductSubscription`` rows (one per Product enum entry)
  3. ``KeelUser.organization`` set to the default org for every existing user

After backfill, adds a ``CheckConstraint`` enforcing the
"non-superuser must have an organization" invariant. The constraint
is added here (post-backfill) rather than in 0010 (pre-backfill)
because pre-backfill every user has ``organization=NULL`` and the
constraint would refuse to apply.

Manual rollback procedure (after 0011 has run):
  1. ``ALTER TABLE keel_user DROP CONSTRAINT keeluser_org_or_superuser;``
  2. ``UPDATE keel_user SET organization_id = NULL;``
  3. ``DELETE FROM keel_org_product_subscription;``
  4. ``DELETE FROM keel_organization WHERE slug = 'docklabs-internal';``
  5. ``python manage.py migrate keel_accounts 0009``
"""
from django.db import migrations, models
from django.utils import timezone

from keel.core.migration_utils import idempotent_backfill


DEFAULT_ORG_SLUG = 'docklabs-internal'
DEFAULT_ORG_NAME = 'DockLabs Internal'

# All product codes the suite ships with. Mirrors keel.accounts.models.Product
# but hardcoded here so the migration is stable even if Product changes
# later (Django historical models don't carry custom code).
SEED_PRODUCT_CODES = [
    'beacon', 'admiralty', 'harbor', 'manifest', 'lookout',
    'bounty', 'purser', 'helm', 'yeoman', 'keel',
]


def seed_default_org_and_backfill(apps, schema_editor):
    """Idempotent: create default org + subs, assign every user."""
    Organization = apps.get_model('keel_accounts', 'Organization')
    OrganizationProductSubscription = apps.get_model(
        'keel_accounts', 'OrganizationProductSubscription'
    )
    KeelUser = apps.get_model('keel_accounts', 'KeelUser')

    # 1. get_or_create the default org. Uses get_or_create (not create)
    #    so a re-run after an interrupted prior run doesn't IntegrityError
    #    on the unique slug. The historical model has no clean()/save()
    #    overrides, so the reserved-slug guard doesn't fire here.
    default_org, _created = Organization.objects.get_or_create(
        slug=DEFAULT_ORG_SLUG,
        defaults={'name': DEFAULT_ORG_NAME, 'is_active': True},
    )

    # 2. Backfill subscription rows. idempotent_backfill skips any
    #    (organization_id, product) pair that already exists, so a
    #    re-run is a no-op even if some rows were committed before
    #    a prior interruption.
    today = timezone.now().date()
    sub_rows = [
        OrganizationProductSubscription(
            organization_id=default_org.id,
            product=code,
            is_active=True,
            started_at=today,
        )
        for code in SEED_PRODUCT_CODES
    ]
    idempotent_backfill(
        OrganizationProductSubscription,
        key_fields=('organization_id', 'product'),
        rows=sub_rows,
    )

    # 3. Assign every existing user (whose organization is null) to
    #    the default org. Bounded UPDATE; one statement, no Python
    #    loop, no per-row save() side effects (good — historical
    #    model has no custom save() anyway, but defensive).
    KeelUser.objects.filter(organization__isnull=True).update(
        organization_id=default_org.id,
    )

    # 4. Backfill any pending Invitation rows to the default org so
    #    pre-rollout invites remain accept-able under the new
    #    accept-time re-validation.
    Invitation = apps.get_model('keel_accounts', 'Invitation')
    Invitation.objects.filter(organization__isnull=True).update(
        organization_id=default_org.id,
    )


def reverse_seed(apps, schema_editor):
    """Reverse: detach users from default org, drop subs, drop org.

    Note: this only runs on explicit ``migrate keel_accounts 0010``.
    Production rollback after 0011 has run requires the manual SQL
    procedure documented in the module docstring (the constraint
    has to come off first or the UPDATE fails).
    """
    Organization = apps.get_model('keel_accounts', 'Organization')
    OrganizationProductSubscription = apps.get_model(
        'keel_accounts', 'OrganizationProductSubscription'
    )
    KeelUser = apps.get_model('keel_accounts', 'KeelUser')
    Invitation = apps.get_model('keel_accounts', 'Invitation')

    try:
        default_org = Organization.objects.get(slug=DEFAULT_ORG_SLUG)
    except Organization.DoesNotExist:
        return

    # Detach users + invitations FIRST so the org can be deleted
    # without violating the PROTECT FK on KeelUser.organization.
    KeelUser.objects.filter(organization_id=default_org.id).update(
        organization_id=None,
    )
    Invitation.objects.filter(organization_id=default_org.id).update(
        organization_id=None,
    )
    OrganizationProductSubscription.objects.filter(
        organization_id=default_org.id
    ).delete()
    default_org.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0010_organization'),
    ]

    operations = [
        migrations.RunPython(
            seed_default_org_and_backfill,
            reverse_code=reverse_seed,
            elidable=False,
        ),
        # Now that every user has an organization (or is_superuser),
        # add the CheckConstraint. Going in this order means the
        # constraint is never in a violated state on disk.
        migrations.AddConstraint(
            model_name='keeluser',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(organization__isnull=False)
                    | models.Q(is_superuser=True)
                ),
                name='keeluser_org_or_superuser',
            ),
        ),
    ]
