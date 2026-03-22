"""Seed demo users with product access for all DockLabs products.

Replaces per-product seed_demo_users commands with a single centralized
command that creates users and grants product access in one step.

Usage:
    python manage.py seed_keel_users
    python manage.py seed_keel_users --product harbor
    python manage.py seed_keel_users --dry-run
"""
import os

from django.core.management.base import BaseCommand

from keel.accounts.models import Agency, KeelUser, ProductAccess

DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo' + '2026!')

# Default demo users per product with their roles
PRODUCT_DEMO_CONFIGS = {
    'beacon': [
        {'role': 'system_admin', 'is_superuser': True},
        {'role': 'agency_admin'},
        {'role': 'relationship_manager'},
        {'role': 'foia_attorney'},
        {'role': 'analyst'},
        {'role': 'executive'},
    ],
    'harbor': [
        {'role': 'system_admin', 'is_superuser': True},
        {'role': 'agency_admin'},
        {'role': 'program_officer'},
        {'role': 'fiscal_officer'},
        {'role': 'reviewer'},
        {'role': 'applicant'},
    ],
    'lookout': [
        {'role': 'admin', 'is_superuser': True},
        {'role': 'legislative_aid'},
        {'role': 'stakeholder'},
    ],
}


class Command(BaseCommand):
    help = 'Seed demo users with centralized Keel accounts and product access.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--product',
            type=str,
            help='Only seed users for a specific product.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without making changes.',
        )

    def handle(self, *args, **options):
        product_filter = options.get('product')
        dry_run = options.get('dry_run', False)

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be made.\n'))

        configs = PRODUCT_DEMO_CONFIGS
        if product_filter:
            if product_filter not in configs:
                self.stderr.write(
                    self.style.ERROR(f'Unknown product: {product_filter}. '
                                     f'Options: {", ".join(configs.keys())}')
                )
                return
            configs = {product_filter: configs[product_filter]}

        # Create a shared admin user that has access to everything
        self._ensure_superadmin(dry_run)

        for product, roles in configs.items():
            self.stdout.write(f'\n--- {product.upper()} ---')
            for role_config in roles:
                self._ensure_demo_user(product, role_config, dry_run)

        self.stdout.write(self.style.SUCCESS('\nDone.'))

    def _ensure_superadmin(self, dry_run):
        """Create a shared admin user with access to all products."""
        username = 'admin'
        if dry_run:
            self.stdout.write(f'  Would create superadmin: {username}')
            return

        user, created = KeelUser.objects.get_or_create(
            username=username,
            defaults={
                'email': 'admin@docklabs.ai',
                'first_name': 'Demo',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
                'is_state_user': True,
                'accepted_terms': True,
            },
        )
        user.set_password(DEMO_PASSWORD)
        user.save()

        # Grant access to all products
        for product in PRODUCT_DEMO_CONFIGS:
            ProductAccess.objects.update_or_create(
                user=user,
                product=product,
                defaults={'role': 'system_admin', 'is_active': True},
            )

        action = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f'  {action} superadmin "{username}" with access to all products'
        ))

    def _ensure_demo_user(self, product, role_config, dry_run):
        """Create a demo user and grant them access to a product."""
        role = role_config['role']
        is_superuser = role_config.get('is_superuser', False)

        # Username format: role for single-product, product_role for multi
        username = role
        display_name = role.replace('_', ' ').title()

        if dry_run:
            self.stdout.write(f'  Would create: {username} → {product} ({role})')
            return

        user, created = KeelUser.objects.get_or_create(
            username=username,
            defaults={
                'email': f'{username}@docklabs.ai',
                'first_name': 'Demo',
                'last_name': display_name,
                'is_staff': is_superuser,
                'is_superuser': is_superuser,
                'is_state_user': True,
                'accepted_terms': True,
            },
        )
        user.set_password(DEMO_PASSWORD)
        user.save()

        access, access_created = ProductAccess.objects.update_or_create(
            user=user,
            product=product,
            defaults={'role': role, 'is_active': True},
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'  Created: {username} → {product} ({role})'))
        else:
            self.stdout.write(f'  Updated: {username} → {product} ({role})')
