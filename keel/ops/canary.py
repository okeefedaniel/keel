"""Canary payload builder.

The four core flags read entirely from keel-shipped tables:

- ``audit_silent_24h`` — no AuditLog rows in 24h (resolved via
  ``settings.KEEL_AUDIT_LOG_MODEL``).
- ``cron_silent_24h`` — no ``keel_scheduling.CommandRun`` rows in 24h.
- ``cron_failures_24h`` — at least one CommandRun with status='error'.
- ``notifications_failing`` — at least one NotificationLog with
  ``success=False`` (resolved via ``settings.KEEL_NOTIFICATION_LOG_MODEL``;
  silently skipped if unset).

A ``None`` counter (model not installed, table missing, query error)
disables its corresponding flag — better to surface "not measured" than
to false-positive. ``healthy`` is True iff every flag is False.
"""
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.utils import timezone


def _safe_count(model_path, **filters):
    """Return a count, or None if the model isn't installed/queryable."""
    if not model_path:
        return None
    try:
        Model = apps.get_model(model_path)
    except (LookupError, ValueError):
        return None
    try:
        return Model.objects.filter(**filters).count()
    except Exception:
        return None


def build_canary_payload(extras_callable=None):
    """Build the canary metrics payload.

    ``extras_callable``, if provided, is called with keyword arguments
    ``now``, ``last_24h``, ``last_1h`` and should return a dict of
    additional counters to merge into the payload. Exceptions raised
    inside it are swallowed — extras are best-effort, the core canary
    must still succeed.
    """
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_1h = now - timedelta(hours=1)

    payload = {
        'generated_at': now.isoformat(),
        'window': {
            'last_24h': last_24h.isoformat(),
            'last_1h': last_1h.isoformat(),
        },
    }

    audit_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    notif_path = getattr(settings, 'KEEL_NOTIFICATION_MODEL', None)
    notif_log_path = getattr(settings, 'KEEL_NOTIFICATION_LOG_MODEL', None)

    payload['audit_log_writes_total'] = _safe_count(audit_path)
    payload['audit_log_writes_24h'] = _safe_count(
        audit_path, timestamp__gte=last_24h,
    )
    payload['audit_log_writes_1h'] = _safe_count(
        audit_path, timestamp__gte=last_1h,
    )

    payload['notifications_sent_total'] = _safe_count(notif_path)
    payload['notifications_sent_24h'] = _safe_count(
        notif_path, created_at__gte=last_24h,
    )
    notifications_failed_24h = _safe_count(
        notif_log_path, created_at__gte=last_24h, success=False,
    )
    payload['notifications_failed_24h'] = notifications_failed_24h

    scheduled_runs_24h = _safe_count(
        'keel_scheduling.CommandRun', started_at__gte=last_24h,
    )
    scheduled_failures_24h = _safe_count(
        'keel_scheduling.CommandRun',
        started_at__gte=last_24h, status='error',
    )
    payload['scheduled_runs_24h'] = scheduled_runs_24h
    payload['scheduled_failures_24h'] = scheduled_failures_24h

    if extras_callable:
        try:
            extras = extras_callable(
                now=now, last_24h=last_24h, last_1h=last_1h,
            )
            if extras:
                payload.update(extras)
        except Exception:
            pass

    flags = {
        'audit_silent_24h': (
            payload['audit_log_writes_24h'] is not None
            and payload['audit_log_writes_24h'] == 0
        ),
        'cron_silent_24h': (
            scheduled_runs_24h is not None and scheduled_runs_24h == 0
        ),
        'cron_failures_24h': (
            scheduled_failures_24h is not None
            and scheduled_failures_24h > 0
        ),
        'notifications_failing': (
            notifications_failed_24h is not None
            and notifications_failed_24h > 0
        ),
    }
    payload['flags'] = flags
    payload['healthy'] = not any(flags.values())
    return payload


FLAG_LABELS = {
    'audit_silent_24h': 'Audit silent (24h)',
    'cron_silent_24h': 'Cron silent (24h)',
    'cron_failures_24h': 'Cron failures (24h)',
    'notifications_failing': 'Notifications failing',
}
