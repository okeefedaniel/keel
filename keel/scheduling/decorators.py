"""``@scheduled_job`` decorator.

Apply to a ``BaseCommand`` subclass to:

1. Register a ``ScheduledJobSpec`` in the module-level registry so
   ``sync_scheduled_jobs`` can upsert the DB row and the dashboard can
   display the job.
2. Wrap ``Command.handle()`` so every invocation writes a ``CommandRun``
   row capturing started_at / finished_at / status / error / duration.

Usage::

    from django.core.management.base import BaseCommand
    from keel.scheduling import scheduled_job

    @scheduled_job(
        slug='helm-notify-due-tasks',
        name='Helm — Daily due-task notifications',
        cron='0 9 * * *',
        owner='helm',
        notes='Fires task_due_soon and task_overdue. Idempotent via Task.last_*_notif_at.',
    )
    class Command(BaseCommand):
        help = 'Fire daily task notifications.'

        def handle(self, *args, **opts):
            ...

The decorator is idempotent — re-applying it (e.g. on test reload) just
re-registers the spec. The wrapper around ``handle()`` is only applied
once per class (guarded by a ``_keel_scheduling_wrapped`` sentinel
attribute).
"""
import functools
import traceback
from typing import Optional

from django.utils import timezone

from keel.scheduling.registry import ScheduledJobSpec, register


_WRAPPED_SENTINEL = '_keel_scheduling_wrapped'


def scheduled_job(
    *,
    slug: str,
    name: str,
    cron: str,
    owner: str,
    command: Optional[str] = None,
    notes: str = '',
    description: str = '',
    timeout_minutes: Optional[int] = None,
):
    """Decorator factory. Returns the actual decorator that wraps a
    ``BaseCommand`` subclass.

    ``command`` defaults to the slug's last segment for display purposes —
    e.g., slug='helm-notify-due-tasks' → command='notify-due-tasks'. If
    your management command name differs from the slug, pass it explicitly.
    """

    def decorator(command_class):
        # Register the spec.
        spec_command = command or slug.rsplit('-', 1)[-1].replace('-', '_')
        register(ScheduledJobSpec(
            slug=slug,
            name=name,
            command=spec_command,
            cron_expression=cron,
            owner_product=owner,
            notes=notes,
            description=description,
            timeout_minutes=timeout_minutes,
        ))

        # Add metadata to the class for introspection.
        command_class._scheduling_slug = slug
        command_class._scheduling_owner = owner
        command_class._scheduling_cron = cron

        # Wrap handle() once — guarded by a sentinel so re-application is a no-op.
        if not getattr(command_class, _WRAPPED_SENTINEL, False):
            original_handle = command_class.handle

            @functools.wraps(original_handle)
            def wrapped_handle(self, *args, **opts):
                # Lazy imports — apps may not be ready when the decorator
                # fires at module load time.
                from keel.scheduling.models import CommandRun, ScheduledJob

                run = None
                try:
                    job = ScheduledJob.objects.filter(slug=slug).first()
                    if job is not None:
                        run = CommandRun.objects.create(
                            job=job, started_at=timezone.now(),
                            status=CommandRun.Status.RUNNING,
                        )
                except Exception:
                    # DB not ready (migrate hasn't run, test setup, etc.) —
                    # never let the run-log machinery break the actual job.
                    run = None

                started = timezone.now() if run is None else run.started_at
                try:
                    result = original_handle(self, *args, **opts)
                    if run is not None:
                        run.status = CommandRun.Status.SUCCESS
                        run.finished_at = timezone.now()
                        run.duration_ms = int(
                            (run.finished_at - started).total_seconds() * 1000
                        )
                        run.save(update_fields=[
                            'status', 'finished_at', 'duration_ms',
                        ])
                    return result
                except Exception as e:
                    if run is not None:
                        run.status = CommandRun.Status.ERROR
                        run.error_message = (
                            f'{type(e).__name__}: {e}\n\n{traceback.format_exc()}'
                        )[:8000]
                        run.finished_at = timezone.now()
                        run.duration_ms = int(
                            (run.finished_at - started).total_seconds() * 1000
                        )
                        run.save(update_fields=[
                            'status', 'finished_at', 'duration_ms', 'error_message',
                        ])
                    raise

            command_class.handle = wrapped_handle
            setattr(command_class, _WRAPPED_SENTINEL, True)

        return command_class

    return decorator
