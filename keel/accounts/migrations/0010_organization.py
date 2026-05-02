"""Schema migration: Organization + OrganizationProductSubscription + FKs.

Adds the org layer. Backfill happens in the next migration (0011) using
``idempotent_backfill`` so a re-run never duplicates seed rows.

Phase ordering (from the plan's Migration path):
  0010 (this) — schema only, nullable FKs
  0011        — data backfill (default org + 9 subs + assign all users)
  0012+       — OIDC claim emission code (separate keel release)

Rolling back 0010 is safe **before** 0011 runs. After 0011, manual cleanup
is required (drop FK constraint, delete seed rows, then migrate accounts
0009). See the plan's Migration path for the documented procedure.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone

import keel.accounts.models  # ensure Product, get_product_choices import time


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0009_invitation_batch_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='Organization',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4,
                    editable=False,
                    primary_key=True,
                    serialize=False,
                )),
                ('slug', models.SlugField(
                    max_length=63,
                    unique=True,
                    help_text=(
                        'Stable identifier used in JWT claims and URLs. '
                        'Lowercase letters, digits, hyphens only.'
                    ),
                )),
                ('name', models.CharField(max_length=255)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('agency', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='organizations',
                    to='keel_accounts.agency',
                    help_text=(
                        'Optional link to the FOIA agency this org represents. '
                        'Independent of KeelUser.agency.'
                    ),
                )),
            ],
            options={
                'db_table': 'keel_organization',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='OrganizationProductSubscription',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4,
                    editable=False,
                    primary_key=True,
                    serialize=False,
                )),
                ('product', models.CharField(
                    max_length=50,
                    help_text='Product code (e.g. harbor, beacon).',
                )),
                ('is_active', models.BooleanField(default=True)),
                ('started_at', models.DateField(default=timezone.now)),
                ('ends_at', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subscriptions',
                    to='keel_accounts.organization',
                )),
            ],
            options={
                'db_table': 'keel_org_product_subscription',
                'ordering': ['organization', 'product'],
                'unique_together': {('organization', 'product')},
            },
        ),
        migrations.AddField(
            model_name='keeluser',
            name='organization',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='users',
                to='keel_accounts.organization',
                help_text=(
                    'DockLabs customer org this user belongs to. Required '
                    'for non-superusers; null only for cross-org admins.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='invitation',
            name='organization',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='invitations',
                to='keel_accounts.organization',
                help_text='DockLabs customer org that granted this invitation.',
            ),
        ),
        # The CheckConstraint that enforces "non-superuser must have org"
        # is added in 0011 *after* the data migration backfills every
        # existing user. Adding it here would refuse to apply because
        # all rows currently violate the constraint.
    ]
