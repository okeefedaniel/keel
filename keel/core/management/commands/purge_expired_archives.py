"""Purge expired archived records.

Works with any product that inherits from keel.core.models.AbstractArchivedRecord.

Usage:
    python manage.py purge_expired_archives
    python manage.py purge_expired_archives --dry-run

Requires KEEL_ARCHIVED_RECORD_MODEL in settings (e.g., 'core.ArchivedRecord').
"""
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Mark expired archived records as purged (skips permanent retention)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be purged without making changes',
        )

    def _get_model(self):
        model_path = getattr(settings, 'KEEL_ARCHIVED_RECORD_MODEL', None)
        if not model_path:
            # Fallback: same app_label as audit log model
            audit_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
            app_label = audit_path.split('.')[0]
            model_path = f'{app_label}.ArchivedRecord'
        return apps.get_model(model_path)

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()
        ArchivedRecord = self._get_model()

        expired = ArchivedRecord.objects.filter(
            retention_expires_at__lt=now,
            is_purged=False,
        ).exclude(
            retention_policy='permanent',
        )

        count = expired.count()
        self.stdout.write(f'Found {count} expired archived record(s).')

        if dry_run:
            self.stdout.write(self.style.WARNING(
                'DRY RUN — no changes will be made'
            ))
            for record in expired[:20]:
                expires = record.retention_expires_at
                self.stdout.write(
                    f'  Would purge: {record.entity_type} '
                    f'{record.entity_id} (expired {expires.date()})'
                )
            if count > 20:
                self.stdout.write(f'  ... and {count - 20} more')
        else:
            updated = expired.update(is_purged=True, purged_at=now)
            self.stdout.write(self.style.SUCCESS(
                f'Marked {updated} archived record(s) as purged.'
            ))
