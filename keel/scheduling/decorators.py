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


def _emit_system_event_from_handle_result(verb: str, result) -> None:
    """Convert a structured ``handle()`` return value to one ``record_system_event``.

    Handler return contract (when ``@scheduled_job(emits=...)`` is set)::

        {
            'summary': str,            # required — one-line narrative
            'status': str,             # optional — 'ok' | 'warn' | 'failed' | 'errored'
            'counts': dict,            # optional — merged into metadata
            'metadata': dict,          # optional — merged into metadata (counts take precedence on collision)
        }

    A return value of None or a non-dict logs a warning and skips emission —
    legacy crons that haven't migrated to the structured contract keep working
    (they just don't appear on ``/ops/`` Row 2 until they migrate). This is
    important for the suite-wide rollout: keel ships the decorator change in
    one PR, products migrate their handlers in follow-up PRs without breakage.
    """
    if result is None:
        import logging
        logging.getLogger(__name__).warning(
            'scheduled_job emits=%r: handle() returned None. Add a structured '
            "return dict like {'summary': '...', 'counts': {...}} to populate "
            'the /ops/ Activity row.',
            verb,
        )
        return
    if not isinstance(result, dict):
        import logging
        logging.getLogger(__name__).warning(
            'scheduled_job emits=%r: handle() returned %s, expected dict. '
            'No Activity row written.',
            verb, type(result).__name__,
        )
        return
    if 'summary' not in result:
        import logging
        logging.getLogger(__name__).warning(
            'scheduled_job emits=%r: handle() return dict missing required '
            "'summary' key. No Activity row written.",
            verb,
        )
        return

    summary = result['summary']
    status = result.get('status', 'ok')
    counts = result.get('counts') or {}
    extra_metadata = result.get('metadata') or {}
    # counts wins on key collision — counts are the structural primitive, extra
    # metadata is freeform. Caller bug if both ship the same key.
    merged_metadata = {**extra_metadata, **counts}

    # Lazy import — keel.activity may load AFTER keel.scheduling.
    from keel.activity.services import record_system_event
    record_system_event(
        verb=verb,
        summary=summary,
        status=status,
        metadata=merged_metadata,
    )


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
    emits: Optional[str] = None,
):
    """Decorator factory. Returns the actual decorator that wraps a
    ``BaseCommand`` subclass.

    ``command`` defaults to the slug's last segment for display purposes —
    e.g., slug='helm-notify-due-tasks' → command='notify-due-tasks'. If
    your management command name differs from the slug, pass it explicitly.

    ``emits``: declarative system-event emission (Approach D, keel ≥ 0.47.0).
    When set to a verb string (e.g. ``'grants_gov.polled'``), the decorator
    wraps ``handle()`` such that the return value is consumed as a structured
    system-event description and one Activity row is created per invocation
    via ``record_system_event()``.

    The handler MUST return a dict with at least ``{'summary': str}`` and may
    include ``{'counts': dict, 'status': str, 'metadata': dict}``. The decorator
    converts that return value to::

        record_system_event(
            verb=<emits value>,
            summary=result['summary'],
            status=result.get('status', 'ok'),
            metadata={**result.get('counts', {}), **result.get('metadata', {})},
        )

    Routine ``status='ok'`` events are pull-only (visible on ``/ops/`` but
    don't notify); ``status in ('failed', 'errored')`` events fan out to
    product ``system_admin``s through the normal Activity → Notification
    pipeline. See ``keel.activity.services.record_system_event`` for details.

    If ``handle()`` returns ``None`` or a non-dict, the decorator falls back
    to CommandRun-only logging and emits a warning. This keeps legacy crons
    that haven't migrated to the structured-return contract working — they
    just don't appear on ``/ops/`` Row 2 until they migrate.

    Example::

        @scheduled_job(
            slug='bounty-grants-gov-poll',
            name='Bounty — Grants.gov hourly poll',
            cron='0 * * * *',
            owner='bounty',
            emits='grants_gov.polled',
        )
        class Command(BaseCommand):
            def handle(self, *args, **opts):
                result = self.run_poll()
                return {
                    'summary': (f'Grants.gov: +{result.new} new, '
                                f'~{result.updated} updated'),
                    'counts': {'new': result.new, 'updated': result.updated},
                    'status': 'ok' if not result.errors else 'warn',
                    'metadata': {'duration_ms': result.duration_ms},
                }
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
                run = None
                try:
                    # Lazy imports — apps may not be ready when the decorator
                    # fires at module load time. Kept INSIDE the try so a
                    # consumer that forgot to add 'keel.scheduling' to
                    # INSTALLED_APPS degrades to "no run-log" rather than
                    # crashing the cron with a RuntimeError on the import.
                    from keel.scheduling.models import CommandRun, ScheduledJob

                    job = ScheduledJob.objects.filter(slug=slug).first()
                    if job is not None:
                        run = CommandRun.objects.create(
                            job=job, started_at=timezone.now(),
                            status=CommandRun.Status.RUNNING,
                        )
                except Exception:
                    # DB not ready (migrate hasn't run, test setup, etc.) or
                    # keel.scheduling not installed — never let the run-log
                    # machinery break the actual job.
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
                    # Declarative system-event emission (Approach D). When the
                    # decorator was applied with emits='verb.name', the handler's
                    # return value drives one Activity row per invocation. Wrapped
                    # in try/except — a botched emit MUST NOT break the cron, which
                    # already succeeded by the time we reach this block.
                    if emits:
                        try:
                            _emit_system_event_from_handle_result(emits, result)
                        except Exception:
                            import logging
                            logging.getLogger(__name__).exception(
                                'scheduled_job(%r) emits=%r: failed to emit '
                                'Activity row from handle() return value. '
                                'CommandRun is still SUCCESS — only the system '
                                'event was dropped.',
                                slug, emits,
                            )
                        # An emits-handler returns a structured dict for the
                        # Activity row — NOT console output. Django's
                        # BaseCommand.execute() does `if output:
                        # self.stdout.write(output)`, which calls
                        # str.endswith() and crashes on a dict
                        # (AttributeError: 'dict' object has no attribute
                        # 'endswith'). We've already consumed `result` for the
                        # emit above, so swallow it here and return None.
                        # Non-emits commands keep returning `result` unchanged
                        # (backwards-compatible — their handle() returns None or
                        # a string per Django convention).
                        return None
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
                    # On exception path, emit a failed system event so /ops/
                    # and the notification fan-out see the failure. Best-effort —
                    # we re-raise either way so the cron exits non-zero.
                    if emits:
                        try:
                            from keel.activity.services import record_system_event
                            record_system_event(
                                verb=emits,
                                summary=f'{slug} failed: {type(e).__name__}: {e}'[:500],
                                status='failed',
                                metadata={
                                    'exception_type': type(e).__name__,
                                    'traceback_head': traceback.format_exc()[:2000],
                                },
                            )
                        except Exception:
                            import logging
                            logging.getLogger(__name__).exception(
                                'scheduled_job(%r) emits=%r: failed to emit '
                                'failure event for exception %s',
                                slug, emits, type(e).__name__,
                            )
                    raise

            command_class.handle = wrapped_handle
            setattr(command_class, _WRAPPED_SENTINEL, True)

        return command_class

    return decorator
