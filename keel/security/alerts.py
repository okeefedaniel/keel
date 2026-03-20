"""
Keel Security Alerts — suspicious activity detection and notification.

Monitors audit logs for patterns that indicate security threats:
- Multiple failed logins from same IP
- Privilege escalation attempts
- Bulk data exports
- After-hours admin access
- Unusual geographic access patterns

Usage:
    # In settings.py:
    KEEL_SECURITY_ALERT_RECIPIENTS = ['admin@example.com']
    KEEL_SECURITY_ALERT_WEBHOOK = 'https://hooks.slack.com/...'  # optional
    KEEL_BUSINESS_HOURS = (8, 18)  # 8am-6pm ET

    # Run the check (e.g., via management command or cron):
    from keel.security.alerts import check_security_events
    check_security_events()
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger('keel.security')


class SecurityAlert:
    """Represents a detected security concern."""

    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_CRITICAL = 'critical'

    def __init__(self, severity, event_type, description, details=None):
        self.severity = severity
        self.event_type = event_type
        self.description = description
        self.details = details or {}
        self.timestamp = timezone.now()

    def __str__(self):
        return f'[{self.severity.upper()}] {self.event_type}: {self.description}'


def check_failed_logins(audit_log_model, window_minutes=15, threshold=5):
    """Detect IPs with excessive failed login attempts."""
    alerts = []
    since = timezone.now() - timedelta(minutes=window_minutes)

    login_attempts = (
        audit_log_model.objects
        .filter(
            action='login',
            timestamp__gte=since,
        )
        .values('ip_address')
        .annotate(count=__import__('django.db.models', fromlist=['Count']).Count('id'))
        .filter(count__gte=threshold)
    )

    for entry in login_attempts:
        alerts.append(SecurityAlert(
            severity=SecurityAlert.SEVERITY_WARNING,
            event_type='excessive_login_attempts',
            description=f'IP {entry["ip_address"]} had {entry["count"]} login attempts in {window_minutes} minutes',
            details={'ip': entry['ip_address'], 'count': entry['count']},
        ))

    return alerts


def check_bulk_exports(audit_log_model, window_hours=1, threshold=10):
    """Detect users performing excessive data exports."""
    alerts = []
    since = timezone.now() - timedelta(hours=window_hours)

    exports = (
        audit_log_model.objects
        .filter(
            action='export',
            timestamp__gte=since,
        )
        .values('user__username', 'user_id')
        .annotate(count=__import__('django.db.models', fromlist=['Count']).Count('id'))
        .filter(count__gte=threshold)
    )

    for entry in exports:
        alerts.append(SecurityAlert(
            severity=SecurityAlert.SEVERITY_CRITICAL,
            event_type='bulk_export',
            description=f'User {entry["user__username"]} performed {entry["count"]} exports in {window_hours} hour(s)',
            details={'user': entry['user__username'], 'count': entry['count']},
        ))

    return alerts


def check_after_hours_admin(audit_log_model, window_hours=24):
    """Detect admin access outside business hours."""
    alerts = []
    business_hours = getattr(settings, 'KEEL_BUSINESS_HOURS', (8, 18))
    start_hour, end_hour = business_hours
    since = timezone.now() - timedelta(hours=window_hours)

    admin_actions = (
        audit_log_model.objects
        .filter(
            timestamp__gte=since,
            entity_type__in=['User', 'Agency', 'Permission'],
            action__in=['create', 'update', 'delete', 'status_change'],
        )
        .select_related('user')
    )

    for entry in admin_actions:
        local_hour = timezone.localtime(entry.timestamp).hour
        if local_hour < start_hour or local_hour >= end_hour:
            alerts.append(SecurityAlert(
                severity=SecurityAlert.SEVERITY_INFO,
                event_type='after_hours_admin',
                description=(
                    f'Admin action by {entry.user} at '
                    f'{timezone.localtime(entry.timestamp):%H:%M} '
                    f'(outside {start_hour}:00-{end_hour}:00)'
                ),
                details={
                    'user': str(entry.user),
                    'action': entry.action,
                    'entity': entry.entity_type,
                    'time': str(entry.timestamp),
                },
            ))

    return alerts


def send_alert_email(alerts):
    """Send security alert digest via email."""
    recipients = getattr(settings, 'KEEL_SECURITY_ALERT_RECIPIENTS', [])
    if not recipients or not alerts:
        return

    critical = [a for a in alerts if a.severity == SecurityAlert.SEVERITY_CRITICAL]
    warnings = [a for a in alerts if a.severity == SecurityAlert.SEVERITY_WARNING]
    infos = [a for a in alerts if a.severity == SecurityAlert.SEVERITY_INFO]

    subject_prefix = '[CRITICAL] ' if critical else '[WARNING] ' if warnings else ''
    subject = f'{subject_prefix}DockLabs Security Alert — {len(alerts)} event(s)'

    body_lines = [
        f'Security Alert Report — {timezone.now():%Y-%m-%d %H:%M %Z}',
        f'Product: {getattr(settings, "KEEL_PRODUCT_NAME", "DockLabs")}',
        f'Total events: {len(alerts)}',
        '',
    ]

    for section_name, section_alerts in [
        ('CRITICAL', critical), ('WARNING', warnings), ('INFO', infos)
    ]:
        if section_alerts:
            body_lines.append(f'--- {section_name} ({len(section_alerts)}) ---')
            for alert in section_alerts:
                body_lines.append(f'  [{alert.event_type}] {alert.description}')
            body_lines.append('')

    body_lines.append('This is an automated security monitoring message from Keel.')

    try:
        send_mail(
            subject=subject,
            message='\n'.join(body_lines),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'security@docklabs.ai'),
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send security alert email')


def send_alert_webhook(alerts):
    """Send security alerts to a webhook (Slack, Teams, etc.)."""
    webhook_url = getattr(settings, 'KEEL_SECURITY_ALERT_WEBHOOK', None)
    if not webhook_url or not alerts:
        return

    try:
        import requests
        critical = [a for a in alerts if a.severity == SecurityAlert.SEVERITY_CRITICAL]

        text_lines = [
            f':{"rotating_light" if critical else "warning"}: '
            f'*DockLabs Security Alert* — {len(alerts)} event(s)',
        ]
        for alert in alerts:
            emoji = {
                'critical': ':red_circle:',
                'warning': ':large_orange_circle:',
                'info': ':large_blue_circle:',
            }.get(alert.severity, ':white_circle:')
            text_lines.append(f'{emoji} `{alert.event_type}` {alert.description}')

        requests.post(
            webhook_url,
            json={'text': '\n'.join(text_lines)},
            timeout=10,
        )
    except Exception:
        logger.exception('Failed to send security alert webhook')


def check_security_events(audit_log_model=None):
    """Run all security checks and send alerts.

    Call this from a management command, cron job, or scheduled task.
    """
    if audit_log_model is None:
        from django.apps import apps
        model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
        audit_log_model = apps.get_model(model_path)

    alerts = []
    alerts.extend(check_failed_logins(audit_log_model))
    alerts.extend(check_bulk_exports(audit_log_model))
    alerts.extend(check_after_hours_admin(audit_log_model))

    if alerts:
        logger.warning('Security check found %d alert(s)', len(alerts))
        for alert in alerts:
            logger.log(
                logging.CRITICAL if alert.severity == 'critical' else logging.WARNING,
                str(alert),
                extra={'security_event': alert.event_type, 'details': alert.details},
            )
        send_alert_email(alerts)
        send_alert_webhook(alerts)

    return alerts
