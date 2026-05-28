"""Canary payload builder.

The five core flags read entirely from keel-shipped tables:

- ``audit_silent_24h`` — no AuditLog rows in 24h (resolved via
  ``settings.KEEL_AUDIT_LOG_MODEL``).
- ``cron_silent_24h`` — no ``keel_scheduling.CommandRun`` rows in 24h.
- ``cron_failures_24h`` — at least one CommandRun with status='error'.
- ``notifications_failing`` — at least one NotificationLog with
  ``success=False`` (resolved via ``settings.KEEL_NOTIFICATION_LOG_MODEL``;
  silently skipped if unset).
- ``audit_constraint_present`` — the DB-level ``auditlog_user_required``
  CheckConstraint exists. If missing, the schema's last line of defense
  against NULL-user audit rows is gone (Approach D guarantee broken).
  Resolved via ``information_schema.check_constraints``; ``None`` on
  non-Postgres backends or query failure (gauge disabled, no flag).

A ``None`` counter (model not installed, table missing, query error)
disables its corresponding flag — better to surface "not measured" than
to false-positive. ``healthy`` is True iff every flag is False.
"""
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.utils import timezone

from keel.core.utils import get_product_code


def user_can_view_canary(user):
    """Return True iff ``user`` may see the ops canary chip row.

    The historical gate (``user.is_staff``) was too loose: ``seed_keel_users``
    force-sets ``is_staff=True`` on every demo user so the Django admin
    works for all role flavors in a demo environment, which means every
    demo agency_admin / analyst / reviewer would see ops infrastructure
    on the dashboard. Per the suite role hierarchy rule (only
    ``system_admin`` and ``is_superuser`` bypass admin-only UI), the
    correct gate is:

    - Django superuser, OR
    - ``system_admin`` ``ProductAccess`` role for this product
      (resolved via ``settings.KEEL_PRODUCT_CODE``).

    Views rendering ``keel/components/canary_flags.html`` should call
    this helper before populating ``canary`` in the template context,
    so the template can stay dumb (``{% if canary %}``).
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    get_role = getattr(user, 'get_product_role', None)
    if not callable(get_role):
        return False
    code = get_product_code()
    if not code:
        return False
    return get_role(code) == 'system_admin'


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


def _check_audit_constraint_present():
    """Return True/False/None for the AuditLog NULL-user protection.

    True means the AuditLog table's ``user_id`` column is NOT NULL — the
    Approach D structural guarantee that no audit row can exist without a
    user. False means the column still allows NULL — the canary should flag,
    because the protection is gone. None means the gauge couldn't be measured
    (model not installed, non-Postgres backend, column/query failure) and the
    flag should stay False (no false positives).

    NOTE: this checks COLUMN NULLABILITY, not a named CheckConstraint. The
    constraint name is templated per concrete subclass
    (``%(app_label)s_%(class)s_user_required``), so a name-based lookup would
    have to know each product's app_label. Column nullability is the actual
    protection and is name-independent — a more robust signal anyway.
    """
    audit_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    if not audit_path:
        return None
    try:
        Model = apps.get_model(audit_path)
    except (LookupError, ValueError):
        return None
    table = Model._meta.db_table
    vendor = getattr(connection, 'vendor', '')
    # information_schema.columns is a Postgres / standard-SQL surface; SQLite
    # doesn't expose it the same way. On non-Postgres vendors we can't verify
    # and disable the gauge.
    if vendor != 'postgresql':
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_name = %s
                  AND column_name = 'user_id'
                LIMIT 1
                """,
                [table],
            )
            row = cursor.fetchone()
        if row is None:
            # Column not found — can't measure; don't false-positive.
            return None
        return row[0] == 'NO'
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

    audit_constraint_present = _check_audit_constraint_present()
    payload['audit_constraint_present'] = audit_constraint_present

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
        # Approach D structural guarantee: the auditlog_user_required
        # CheckConstraint MUST be present. Only flag when we measured
        # False (constraint missing); None disables the flag entirely.
        'audit_constraint_missing': (
            audit_constraint_present is False
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
    'audit_constraint_missing': 'Audit constraint missing',
}
