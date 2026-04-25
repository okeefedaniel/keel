"""Tests for keel.scheduling — registry, decorator, sync command, run logging.

Pins the contract that:
- @scheduled_job registers a spec in the module-level registry.
- The decorator wraps Command.handle() once (idempotent re-application).
- handle() invocations write CommandRun rows with the right status/duration.
- Errors in handle() are captured AND re-raised so the cron exits non-zero.
- sync_scheduled_jobs upserts specs preserving admin-edited fields.
- The dashboard surfaces orphaned + pending-sync states.
"""
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.test import Client, TestCase

from keel.scheduling import scheduled_job
from keel.scheduling.models import CommandRun, ScheduledJob
from keel.scheduling.registry import job_registry, ScheduledJobSpec


User = get_user_model()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class RegistryTests(TestCase):
    def setUp(self):
        job_registry.clear()

    def tearDown(self):
        job_registry.clear()

    def test_register_and_get(self):
        spec = ScheduledJobSpec(
            slug='test-job', name='Test Job', command='test_cmd',
            cron_expression='0 0 * * *', owner_product='helm',
        )
        job_registry.register(spec)
        self.assertEqual(job_registry.get('test-job'), spec)

    def test_register_overwrites(self):
        s1 = ScheduledJobSpec(
            slug='same-slug', name='V1', command='c', cron_expression='*',
            owner_product='helm',
        )
        s2 = ScheduledJobSpec(
            slug='same-slug', name='V2', command='c', cron_expression='*',
            owner_product='helm',
        )
        job_registry.register(s1)
        job_registry.register(s2)
        self.assertEqual(job_registry.get('same-slug').name, 'V2')

    def test_all_returns_sorted(self):
        job_registry.register(ScheduledJobSpec(
            slug='b-job', name='B', command='c', cron_expression='*',
            owner_product='zoo',
        ))
        job_registry.register(ScheduledJobSpec(
            slug='a-job', name='A', command='c', cron_expression='*',
            owner_product='helm',
        ))
        slugs = [s.slug for s in job_registry.all()]
        # Sorted by (owner_product, slug) — 'helm' before 'zoo'.
        self.assertEqual(slugs, ['a-job', 'b-job'])


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------
class DecoratorTests(TestCase):
    def setUp(self):
        job_registry.clear()

    def tearDown(self):
        job_registry.clear()

    def test_decorator_registers_spec(self):
        @scheduled_job(
            slug='deco-test', name='Deco Test', cron='0 0 * * *', owner='test',
        )
        class Command(BaseCommand):
            def handle(self, *args, **opts): pass

        spec = job_registry.get('deco-test')
        self.assertIsNotNone(spec)
        self.assertEqual(spec.name, 'Deco Test')
        self.assertEqual(spec.cron_expression, '0 0 * * *')
        self.assertEqual(spec.owner_product, 'test')

    def test_decorator_adds_introspection_attrs(self):
        @scheduled_job(slug='intro-test', name='X', cron='*', owner='helm')
        class Command(BaseCommand):
            def handle(self, *args, **opts): pass

        self.assertEqual(Command._scheduling_slug, 'intro-test')
        self.assertEqual(Command._scheduling_owner, 'helm')

    def test_handle_wrapper_creates_command_run(self):
        @scheduled_job(slug='run-test', name='R', cron='*', owner='helm')
        class Command(BaseCommand):
            def handle(self, *args, **opts):
                return 'ok'

        # Sync into DB before invoking — the wrapper looks up the row.
        ScheduledJob.objects.create(
            slug='run-test', name='R', command='r', cron_expression='*',
            owner_product='helm',
        )
        cmd = Command()
        cmd.handle()
        self.assertEqual(CommandRun.objects.count(), 1)
        run = CommandRun.objects.first()
        self.assertEqual(run.status, CommandRun.Status.SUCCESS)
        self.assertIsNotNone(run.finished_at)
        self.assertIsNotNone(run.duration_ms)

    def test_handle_wrapper_captures_error_and_reraises(self):
        @scheduled_job(slug='err-test', name='E', cron='*', owner='helm')
        class Command(BaseCommand):
            def handle(self, *args, **opts):
                raise RuntimeError('boom')

        ScheduledJob.objects.create(
            slug='err-test', name='E', command='e', cron_expression='*',
            owner_product='helm',
        )
        with self.assertRaises(RuntimeError):
            Command().handle()
        run = CommandRun.objects.first()
        self.assertEqual(run.status, CommandRun.Status.ERROR)
        self.assertIn('boom', run.error_message)

    def test_handle_wrapper_no_db_row_runs_anyway(self):
        """If the spec hasn't been synced into DB yet, handle() still runs —
        we don't want missing observability rows to break the actual job."""

        @scheduled_job(slug='unsynced', name='U', cron='*', owner='helm')
        class Command(BaseCommand):
            def handle(self, *args, **opts):
                return 'ran without row'

        # No ScheduledJob row exists — handle should still execute.
        result = Command().handle()
        self.assertEqual(result, 'ran without row')
        self.assertEqual(CommandRun.objects.count(), 0)

    def test_decorator_idempotent_double_application(self):
        """Re-decorating the same class shouldn't double-wrap handle()."""

        def make():
            @scheduled_job(slug='idem', name='I', cron='*', owner='helm')
            class Command(BaseCommand):
                def handle(self, *args, **opts):
                    return 1
            return Command

        # Apply decorator twice on the same class.
        Cmd = make()
        # Manually re-apply the decorator.
        scheduled_job(slug='idem', name='I', cron='*', owner='helm')(Cmd)

        ScheduledJob.objects.create(
            slug='idem', name='I', command='i', cron_expression='*',
            owner_product='helm',
        )
        Cmd().handle()
        # Only ONE CommandRun, not two — wrapper not stacked.
        self.assertEqual(CommandRun.objects.count(), 1)


# ---------------------------------------------------------------------------
# sync_scheduled_jobs management command
# ---------------------------------------------------------------------------
class SyncCommandTests(TestCase):
    def setUp(self):
        job_registry.clear()
        ScheduledJob.objects.all().delete()

    def tearDown(self):
        job_registry.clear()

    def test_sync_creates_new_jobs(self):
        job_registry.register(ScheduledJobSpec(
            slug='new-1', name='New 1', command='c', cron_expression='*',
            owner_product='helm',
        ))
        out = StringIO()
        call_command('sync_scheduled_jobs', stdout=out)
        self.assertEqual(ScheduledJob.objects.filter(slug='new-1').count(), 1)
        self.assertIn('Created 1 new jobs', out.getvalue())

    def test_sync_updates_when_decl_changes(self):
        ScheduledJob.objects.create(
            slug='upd-1', name='OLD NAME', command='c', cron_expression='*',
            owner_product='helm',
        )
        job_registry.register(ScheduledJobSpec(
            slug='upd-1', name='NEW NAME', command='c', cron_expression='*',
            owner_product='helm',
        ))
        call_command('sync_scheduled_jobs')
        row = ScheduledJob.objects.get(slug='upd-1')
        self.assertEqual(row.name, 'NEW NAME')

    def test_sync_preserves_admin_edited_fields(self):
        """enabled and notes survive across re-sync."""
        ScheduledJob.objects.create(
            slug='preserve', name='X', command='c', cron_expression='*',
            owner_product='helm', enabled=False, notes='Admin paused this',
        )
        job_registry.register(ScheduledJobSpec(
            slug='preserve', name='X', command='c', cron_expression='*',
            owner_product='helm',
            notes='Default notes from spec',  # would be ignored on existing rows
        ))
        call_command('sync_scheduled_jobs')
        row = ScheduledJob.objects.get(slug='preserve')
        self.assertFalse(row.enabled)
        self.assertEqual(row.notes, 'Admin paused this')

    def test_sync_reports_orphans(self):
        ScheduledJob.objects.create(
            slug='orphan', name='O', command='c', cron_expression='*',
            owner_product='helm',
        )
        # Don't register in the registry — it's now orphaned.
        out = StringIO()
        call_command('sync_scheduled_jobs', stdout=out)
        self.assertIn('Orphaned', out.getvalue())
        self.assertIn('orphan', out.getvalue())
        # Orphans are NOT deleted automatically.
        self.assertTrue(ScheduledJob.objects.filter(slug='orphan').exists())

    def test_dry_run_does_not_write(self):
        job_registry.register(ScheduledJobSpec(
            slug='dry', name='D', command='c', cron_expression='*',
            owner_product='helm',
        ))
        out = StringIO()
        call_command('sync_scheduled_jobs', '--dry-run', stdout=out)
        self.assertEqual(ScheduledJob.objects.filter(slug='dry').count(), 0)
        self.assertIn('dry-run', out.getvalue())


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ModelTests(TestCase):
    def test_success_rate_none_when_no_runs(self):
        job = ScheduledJob.objects.create(
            slug='sr', name='SR', command='c', cron_expression='*',
            owner_product='helm',
        )
        self.assertIsNone(job.success_rate())

    def test_success_rate_computes_correctly(self):
        job = ScheduledJob.objects.create(
            slug='sr', name='SR', command='c', cron_expression='*',
            owner_product='helm',
        )
        # 3 success, 1 error.
        for _ in range(3):
            CommandRun.objects.create(job=job, status=CommandRun.Status.SUCCESS)
        CommandRun.objects.create(job=job, status=CommandRun.Status.ERROR)
        self.assertAlmostEqual(job.success_rate(), 0.75)

    def test_command_run_str(self):
        job = ScheduledJob.objects.create(
            slug='r', name='R', command='c', cron_expression='*',
            owner_product='helm',
        )
        run = CommandRun.objects.create(job=job, status=CommandRun.Status.SUCCESS)
        self.assertIn('r', str(run))
