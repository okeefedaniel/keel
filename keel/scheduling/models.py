"""Concrete models for the scheduling registry + run log.

Both tables live in keel directly (not abstract). Each product service
deploys its own keel install, gets its own copy of these tables, and
its own dashboard at /scheduling/ showing only that service's jobs.

There is no cross-service aggregation — a future "fleet scheduling"
view in Helm could pull each product's jobs via its helm-feed, but
v1 keeps each service self-contained.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class ScheduledJob(models.Model):
    """A registered scheduled command. Synced from the @scheduled_job
    decorator registry by the ``sync_scheduled_jobs`` management command.

    ``enabled`` and ``notes`` are admin-editable — they survive across
    deploys and re-syncs. Other fields are owned by the code declaration.
    """

    slug = models.SlugField(max_length=120, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    command = models.CharField(
        max_length=120,
        help_text='Django management command (e.g., notify_due_tasks).',
    )
    cron_expression = models.CharField(
        max_length=64, blank=True,
        help_text='Display-only schedule (e.g., "0 9 * * *"). The cron itself runs externally.',
    )
    owner_product = models.CharField(
        max_length=32, db_index=True,
        help_text="Which product declared this job — 'helm', 'admiralty', etc.",
    )
    description = models.TextField(blank=True)
    timeout_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='If a run exceeds this, the dashboard flags it as overdue.',
    )

    # Admin-editable fields — preserved across syncs.
    enabled = models.BooleanField(
        default=True,
        help_text='Display flag — does NOT actually pause the cron. Manage that '
                  'in Railway / your scheduler. Use this to mark jobs as '
                  'expected-disabled so the dashboard does not flag missing runs.',
    )
    notes = models.TextField(
        blank=True,
        help_text='Admin notes — runbook URL, escalation path, etc.',
    )

    declared_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner_product', 'slug']
        indexes = [
            models.Index(fields=['owner_product', 'enabled']),
        ]

    def __str__(self):
        return f'{self.owner_product}: {self.name}'

    def latest_run(self):
        return self.runs.order_by('-started_at').first()

    def recent_runs(self, n: int = 24):
        return list(self.runs.order_by('-started_at')[:n])

    def success_rate(self) -> float | None:
        """Fraction of recent_runs (24) that succeeded. None if no runs."""
        runs = self.recent_runs(24)
        if not runs:
            return None
        ok = sum(1 for r in runs if r.status == CommandRun.Status.SUCCESS)
        return ok / len(runs)


class CommandRun(models.Model):
    """One invocation of a scheduled job.

    Created by the @scheduled_job decorator's wrapper around handle().
    Persists outcome + duration + error so the dashboard can show
    last-N-runs at a glance.
    """

    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        ERROR = 'error', 'Error'
        SKIPPED = 'skipped', 'Skipped'

    job = models.ForeignKey(
        ScheduledJob, on_delete=models.CASCADE, related_name='runs',
    )
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RUNNING, db_index=True,
    )
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    # Optional attribution — when an admin invoked the command via shell.
    invoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['job', '-started_at']),
            models.Index(fields=['status', '-started_at']),
        ]

    def __str__(self):
        return f'{self.job.slug} @ {self.started_at:%Y-%m-%d %H:%M} → {self.status}'

    @property
    def is_running(self) -> bool:
        return self.status == self.Status.RUNNING

    @property
    def is_failed(self) -> bool:
        return self.status == self.Status.ERROR
