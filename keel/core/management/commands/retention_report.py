"""Generate a retention compliance report for archived records.

Usage:
    python manage.py retention_report
    python manage.py retention_report --json

Requires KEEL_ARCHIVED_RECORD_MODEL in settings (e.g., 'core.ArchivedRecord').
"""
import json

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone


class Command(BaseCommand):
    help = 'Generate a retention compliance report for archived records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output report as JSON',
        )

    def _get_model(self):
        model_path = getattr(settings, 'KEEL_ARCHIVED_RECORD_MODEL', None)
        if not model_path:
            audit_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
            app_label = audit_path.split('.')[0]
            model_path = f'{app_label}.ArchivedRecord'
        return apps.get_model(model_path)

    def handle(self, *args, **options):
        now = timezone.now()
        ArchivedRecord = self._get_model()

        total = ArchivedRecord.objects.count()
        purged = ArchivedRecord.objects.filter(is_purged=True).count()
        active = total - purged

        expired_unpurged = ArchivedRecord.objects.filter(
            retention_expires_at__lt=now,
            is_purged=False,
        ).exclude(retention_policy='permanent').count()

        by_policy = dict(
            ArchivedRecord.objects.filter(is_purged=False)
            .values_list('retention_policy')
            .annotate(count=Count('id'))
            .values_list('retention_policy', 'count')
        )

        by_type = dict(
            ArchivedRecord.objects.filter(is_purged=False)
            .values_list('entity_type')
            .annotate(count=Count('id'))
            .values_list('entity_type', 'count')
        )

        report = {
            'generated_at': now.isoformat(),
            'total_records': total,
            'active_records': active,
            'purged_records': purged,
            'expired_awaiting_purge': expired_unpurged,
            'by_retention_policy': by_policy,
            'by_entity_type': by_type,
        }

        if options['json']:
            self.stdout.write(json.dumps(report, indent=2))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING('Retention Report'))
            self.stdout.write(f'  Generated: {now:%Y-%m-%d %H:%M}')
            self.stdout.write(f'  Total archived records: {total}')
            self.stdout.write(f'  Active (not purged): {active}')
            self.stdout.write(f'  Purged: {purged}')
            if expired_unpurged:
                self.stdout.write(self.style.WARNING(
                    f'  Expired awaiting purge: {expired_unpurged}'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    '  Expired awaiting purge: 0'
                ))
            self.stdout.write('\n  By retention policy:')
            for policy, count in sorted(by_policy.items()):
                self.stdout.write(f'    {policy}: {count}')
            self.stdout.write('\n  By entity type:')
            for etype, count in sorted(by_type.items()):
                self.stdout.write(f'    {etype}: {count}')
