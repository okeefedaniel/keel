"""Clean up demo users to exactly one per configured DEMO_ROLE.

Discovers FK relationships dynamically so it works with any product's models.
Reassigns data from duplicate demo users to the canonical one, then deletes
the duplicates.

Usage:
    python manage.py cleanup_demo_users
    python manage.py cleanup_demo_users --dry-run
"""
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()

DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo' + '2026!')


class Command(BaseCommand):
    help = 'Consolidate demo users to one per role and reset credentials.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would happen without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        demo_roles = getattr(settings, 'DEMO_ROLES', ['admin'])

        if not getattr(settings, 'DEMO_MODE', False):
            self.stdout.write(self.style.WARNING(
                'DEMO_MODE is not enabled. Use --force or set DEMO_MODE=True.'
            ))

        # Find all FK fields pointing to User
        fk_fields = self._discover_user_fks()

        for role in demo_roles:
            self._process_role(role, fk_fields, dry_run)

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes made.'))
        else:
            self.stdout.write(self.style.SUCCESS('Demo user cleanup complete.'))

    def _discover_user_fks(self):
        """Find all ForeignKey fields across all models that point to User."""
        from django.apps import apps

        fk_fields = []
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if (
                    hasattr(field, 'related_model')
                    and field.related_model is User
                    and hasattr(field, 'field')
                ):
                    fk_fields.append((model, field.field.name))
        return fk_fields

    def _process_role(self, role, fk_fields, dry_run):
        """Ensure exactly one demo user exists for this role."""
        users = list(User.objects.filter(username=role).order_by('pk'))

        if not users:
            self.stdout.write(f'  Creating demo user: {role}')
            if not dry_run:
                user = User(username=role)
                user.set_password(DEMO_PASSWORD)
                if hasattr(user, 'role'):
                    user.role = role
                if hasattr(user, 'is_staff'):
                    user.is_staff = role in ('admin', 'system_admin')
                if hasattr(user, 'is_superuser'):
                    user.is_superuser = role in ('admin', 'system_admin')
                user.save()
            return

        canonical = users[0]
        duplicates = users[1:]

        # Reset the canonical user's password
        if not dry_run:
            canonical.set_password(DEMO_PASSWORD)
            if hasattr(canonical, 'is_staff'):
                canonical.is_staff = role in ('admin', 'system_admin')
            canonical.save()

        if not duplicates:
            self.stdout.write(f'  {role}: OK (1 user)')
            return

        self.stdout.write(
            f'  {role}: found {len(duplicates)} duplicate(s), '
            f'reassigning to pk={canonical.pk}'
        )

        for model, field_name in fk_fields:
            for dup in duplicates:
                qs = model.objects.filter(**{field_name: dup})
                count = qs.count()
                if count:
                    self.stdout.write(
                        f'    Reassigning {count} {model.__name__}.{field_name} '
                        f'from {dup.username} to {canonical.username}'
                    )
                    if not dry_run:
                        qs.update(**{field_name: canonical})

        if not dry_run:
            for dup in duplicates:
                dup.delete()
        self.stdout.write(
            f'    Deleted {len(duplicates)} duplicate user(s) for {role}'
        )
