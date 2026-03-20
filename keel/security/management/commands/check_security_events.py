"""
Management command to check for security events and send alerts.

Usage:
    python manage.py check_security_events

Schedule via cron every 15 minutes:
    */15 * * * * cd /app && python manage.py check_security_events
"""
from django.core.management.base import BaseCommand

from keel.security.alerts import check_security_events


class Command(BaseCommand):
    help = 'Check audit logs for suspicious security events and send alerts'

    def handle(self, *args, **options):
        alerts = check_security_events()
        if alerts:
            self.stdout.write(self.style.WARNING(f'Found {len(alerts)} security alert(s):'))
            for alert in alerts:
                self.stdout.write(f'  [{alert.severity.upper()}] {alert.event_type}: {alert.description}')
        else:
            self.stdout.write(self.style.SUCCESS('No security events detected.'))
