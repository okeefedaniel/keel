"""Ensure the platform bootstrap superuser exists.

dokadmin is the canonical superuser across every DockLabs product.
Keel's OIDC JWT carries preferred_username=dokadmin, and every
product's KeelSocialAccountAdapter matches that claim against the
local username field first before falling back to email. If
dokadmin doesn't exist in a product's DB, SSO fails with "Signup
currently closed" because allauth can't auto-create without it.

This command is called unconditionally by keel.core.startup.run_startup()
so every fresh Railway deployment (prod or demo) has dokadmin available
immediately after first boot. Idempotent — re-running is a no-op.

Separate from seed_keel_users (which is demo-only and creates all the
per-product demo users). dokadmin is the ONE user that must exist in
prod too.
"""
import os

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Ensure the dokadmin bootstrap superuser exists with ProductAccess on all known products."

    def handle(self, *args, **options):
        from keel.accounts.models import KeelUser, ProductAccess, PRODUCT_ROLES

        username = 'dokadmin'
        email = os.environ.get('DOKADMIN_EMAIL', 'dok@dok.net')

        with transaction.atomic():
            user, created = KeelUser.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'is_superuser': True,
                    'is_staff': True,
                    'is_active': True,
                    'first_name': 'Dan',
                    'last_name': "O'Keefe",
                },
            )
            if created:
                # Set a random password — real auth goes through OIDC, but
                # Django requires a usable hash for is_superuser actions
                # like /admin/ access outside SSO.
                user.set_unusable_password()
                user.save(update_fields=['password'])
                self.stdout.write(self.style.SUCCESS(f'  Created: {username} ({email})'))
            else:
                # Ensure ongoing invariants in case the row drifted
                changed = False
                if not user.is_superuser:
                    user.is_superuser = True
                    changed = True
                if not user.is_staff:
                    user.is_staff = True
                    changed = True
                if not user.is_active:
                    user.is_active = True
                    changed = True
                if changed:
                    user.save(update_fields=['is_superuser', 'is_staff', 'is_active'])
                    self.stdout.write(self.style.WARNING(f'  Restored superuser flags: {username}'))
                else:
                    self.stdout.write(f'  Exists: {username}')

            # Grant system_admin on every product keel knows about.
            # This is a small, bounded set — PRODUCT_ROLES is the source
            # of truth for valid product codes.
            for product_code in PRODUCT_ROLES.keys():
                ProductAccess.objects.update_or_create(
                    user=user,
                    product=product_code,
                    defaults={'role': 'system_admin', 'is_active': True},
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ProductAccess: system_admin on {len(PRODUCT_ROLES)} products'
                )
            )
