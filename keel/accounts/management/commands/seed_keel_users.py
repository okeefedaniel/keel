"""Seed demo users with product access for all DockLabs products.

Dynamically reads roles from PRODUCT_ROLES so every product gets demo
users without maintaining a separate hardcoded list.

Usage:
    python manage.py seed_keel_users
    python manage.py seed_keel_users --product harbor
    python manage.py seed_keel_users --dry-run
"""
import os

from django.core.management.base import BaseCommand

from keel.accounts.models import Agency, KeelUser, PRODUCT_ROLES, ProductAccess

DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo' + '2026!')

# Roles that indicate a superuser / admin account (first match wins).
_ADMIN_ROLE_KEYWORDS = ('system_admin', 'admin')


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

        # Derive configs dynamically from the canonical PRODUCT_ROLES registry.
        configs = {
            product: self._roles_to_configs(roles)
            for product, roles in PRODUCT_ROLES.items()
            if product != 'keel'  # skip keel-internal roles
        }

        if product_filter:
            if product_filter not in configs:
                self.stderr.write(
                    self.style.ERROR(f'Unknown product: {product_filter}. '
                                     f'Options: {", ".join(configs.keys())}')
                )
                return
            configs = {product_filter: configs[product_filter]}

        # Create a shared admin user that has access to everything
        self._ensure_superadmin(configs, dry_run)

        for product, roles in configs.items():
            self.stdout.write(f'\n--- {product.upper()} ---')
            for role_config in roles:
                self._ensure_demo_user(product, role_config, dry_run)

        self.stdout.write(self.style.SUCCESS('\nDone.'))

    @staticmethod
    def _roles_to_configs(role_tuples):
        """Convert PRODUCT_ROLES tuples to seed configs.

        The first role whose slug contains an admin keyword is marked as
        superuser.  All roles get a demo user.
        """
        configs = []
        found_admin = False
        for slug, _label in role_tuples:
            is_admin = (
                not found_admin
                and any(kw in slug for kw in _ADMIN_ROLE_KEYWORDS)
            )
            if is_admin:
                found_admin = True
            configs.append({'role': slug, 'is_superuser': is_admin})
        return configs

    def _ensure_superadmin(self, configs, dry_run):
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

        # Grant access to all products being seeded
        for product in configs:
            # Use the first admin role for this product, fallback to first role
            admin_role = next(
                (c['role'] for c in configs[product] if c.get('is_superuser')),
                configs[product][0]['role'],
            )
            ProductAccess.objects.update_or_create(
                user=user,
                product=product,
                defaults={'role': admin_role, 'is_active': True},
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

        # All demo users get is_staff=True so they can reach staff-gated
        # views (e.g. manifest's AgencyStaffRequiredMixin falls back to a
        # plain is_staff check in standalone mode). is_superuser is still
        # reserved for admin-role accounts.
        user, created = KeelUser.objects.get_or_create(
            username=username,
            defaults={
                'email': f'{username}@docklabs.ai',
                'first_name': 'Demo',
                'last_name': display_name,
                'is_staff': True,
                'is_superuser': is_superuser,
                'is_state_user': True,
                'accepted_terms': True,
            },
        )
        # Ensure is_staff stays True on re-seeds of existing users.
        user.is_staff = True
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
