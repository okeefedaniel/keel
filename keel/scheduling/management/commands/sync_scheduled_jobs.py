"""Sync the in-code @scheduled_job declarations into the ScheduledJob table.

Idempotent. Run this on every deploy (e.g., from startup.py) so the
admin dashboard stays in sync with what's declared in code. Admin-edited
fields (``enabled``, ``notes``) are preserved across runs — only
declaration-owned fields (name, command, cron_expression, owner_product,
description, timeout_minutes) are overwritten.

Reports:
- Created: new jobs that weren't in the DB.
- Updated: existing jobs whose declaration changed.
- Orphaned: DB rows whose decorator was removed from code.

Orphans are flagged in the report and on the dashboard but not deleted —
admins decide whether to clean them up. (A removed cron is rarely
intentional; better to surface it than silently lose history.)
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from keel.scheduling.models import ScheduledJob
from keel.scheduling.registry import job_registry


class Command(BaseCommand):
    help = 'Sync @scheduled_job declarations into the ScheduledJob table.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would change without writing to the DB.',
        )

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        specs = job_registry.all()
        existing = {j.slug: j for j in ScheduledJob.objects.all()}

        created = []
        updated = []
        unchanged = []

        for spec in specs:
            row = existing.get(spec.slug)
            decl_fields = {
                'name': spec.name,
                'command': spec.command,
                'cron_expression': spec.cron_expression,
                'owner_product': spec.owner_product,
                'description': spec.description,
                'timeout_minutes': spec.timeout_minutes,
            }
            if row is None:
                if not dry:
                    ScheduledJob.objects.create(
                        slug=spec.slug,
                        notes=spec.notes,  # initial notes from spec
                        declared_at=timezone.now(),
                        **decl_fields,
                    )
                created.append(spec.slug)
                continue
            # Compute diff vs DB.
            changed = {f: v for f, v in decl_fields.items() if getattr(row, f) != v}
            if changed:
                if not dry:
                    for f, v in changed.items():
                        setattr(row, f, v)
                    row.save(update_fields=list(changed.keys()) + ['updated_at'])
                updated.append((spec.slug, list(changed.keys())))
            else:
                unchanged.append(spec.slug)

        # Orphaned: in DB but no longer declared.
        declared_slugs = {s.slug for s in specs}
        orphaned = [slug for slug in existing if slug not in declared_slugs]

        # Report.
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'Created {len(created)} new jobs:'
            ))
            for slug in created:
                self.stdout.write(f'  + {slug}')
        if updated:
            self.stdout.write(self.style.WARNING(
                f'Updated {len(updated)} jobs:'
            ))
            for slug, fields in updated:
                self.stdout.write(f'  ~ {slug} ({", ".join(fields)})')
        if unchanged:
            self.stdout.write(
                f'Unchanged: {len(unchanged)} job(s) already in sync.'
            )
        if orphaned:
            self.stdout.write(self.style.ERROR(
                f'Orphaned (in DB but no longer declared): {len(orphaned)}'
            ))
            for slug in orphaned:
                self.stdout.write(f'  ! {slug}')
            self.stdout.write(self.style.WARNING(
                'Orphaned jobs are NOT deleted automatically — '
                'review and clean up manually if intentional.'
            ))
        if dry:
            self.stdout.write(self.style.WARNING('(dry-run — no changes written)'))
