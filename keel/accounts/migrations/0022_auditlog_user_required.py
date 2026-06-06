"""v0.46.0 — Approach D schema-enforced AuditLog.user NOT NULL.

Under the new audit pipeline, AuditLog is exclusively for user actions.
System events (cron polls, cache refreshes, failed logins, lockouts) flow
through Activity via record_system_event(). The schema constraint here is
the structural enforcement.

This migration assumes the consumer's pre-deploy step pruned any
``user_id IS NULL`` rows (see Phase 3 of the spec — bounty's TRUNCATE copy-
and-swap). If any NULL-user rows exist when the migration runs, the
``SET NOT NULL`` step raises ``NotNullViolation`` and aborts — that's the
desired safety net.
"""
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0021_keeluser_email_lower_idx'),
    ]

    operations = [
        # 1. Drop the LOGIN_FAILED / SECURITY_EVENT choices (advisory).
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('create', 'Create'), ('update', 'Update'),
                    ('delete', 'Delete'),
                    ('status_change', 'Status Change'),
                    ('submit', 'Submit'), ('approve', 'Approve'),
                    ('reject', 'Reject'), ('login', 'Login'),
                    ('export', 'Export'), ('view', 'View'),
                    ('role_grant_denied', 'Role Grant Denied'),
                    ('ai_key_fetch', 'AI Key Fetch'),
                ],
                max_length=25,
            ),
        ),
        # 2. Tighten user FK: null=False, on_delete=PROTECT.
        migrations.AlterField(
            model_name='auditlog',
            name='user',
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name='audit_logs',
                to=settings.AUTH_USER_MODEL,
                help_text=(
                    'Required — AuditLog is user-only under Approach D '
                    '(see AbstractAuditLog docstring).'
                ),
            ),
        ),
        # 3. Add the defense-in-depth CheckConstraint.
        migrations.AddConstraint(
            model_name='auditlog',
            constraint=models.CheckConstraint(
                # `condition=` is the Django 5.2+ name (`check=` removed in 6.0).
                condition=models.Q(user__isnull=False),
                name='auditlog_user_required',
            ),
        ),
    ]
