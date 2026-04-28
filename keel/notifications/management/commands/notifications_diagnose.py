"""Explain why (or why not) a user would receive each registered notification.

Usage:
    python manage.py notifications_diagnose <email>

Prints, for the user identified by email:
  - Active ProductAccess rows
  - For each registered NotificationType: would this user be a recipient,
    which channels would fire, and what (if anything) blocks delivery
  - Last 20 NotificationLog entries

Use this to debug "I didn't get a notification" reports without reading
dispatch.py + querying the DB by hand.
"""
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from keel.notifications.dispatch import _get_user_preference, _resolve_recipients
from keel.notifications.registry import get_all_types


class Command(BaseCommand):
    help = 'Diagnose notification routing for a single user.'

    def add_arguments(self, parser):
        parser.add_argument('email', help='User email address')

    def handle(self, *args, **options):
        User = get_user_model()
        email = options['email']
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError(f'No user with email {email!r}')

        product = (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower() or '(unset)'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n=== Notification diagnosis for {user.email} (product={product}) ==='
        ))

        self._print_product_access(user)
        self._print_notification_types(user)
        self._print_recent_logs(user)

    def _print_product_access(self, user):
        self.stdout.write(self.style.MIGRATE_LABEL('\nActive ProductAccess rows:'))
        try:
            from keel.accounts.models import ProductAccess
        except Exception:
            self.stdout.write('  (ProductAccess model not available)')
            return
        rows = ProductAccess.objects.filter(user=user, is_active=True)
        if not rows:
            self.stdout.write(self.style.WARNING('  (none — user has no active product access)'))
            return
        for pa in rows:
            self.stdout.write(f'  product={pa.product:<12} role={pa.role}')

    def _print_notification_types(self, user):
        self.stdout.write(self.style.MIGRATE_LABEL('\nRegistered NotificationTypes (this product):'))
        types = get_all_types()
        if not types:
            self.stdout.write('  (none registered)')
            return
        product = (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower()
        for key, ntype in sorted(types.items()):
            self.stdout.write(f'\n  {self.style.HTTP_INFO(key)}')
            self.stdout.write(f'    label:           {ntype.label}')
            self.stdout.write(f'    default_channels: {ntype.default_channels}')
            self.stdout.write(f'    default_roles:   {ntype.default_roles}')

            recipients = _resolve_recipients(ntype, context={})
            would_match = any(r.pk == user.pk for r in recipients)
            if would_match:
                self.stdout.write(self.style.SUCCESS(
                    f'    → user IS a default recipient ({len(recipients)} total)'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'    → user is NOT a default recipient '
                    f'({len(recipients)} other users would receive)'
                ))
                if ntype.default_roles and 'all' not in ntype.default_roles:
                    self.stdout.write(
                        f'      (needs ProductAccess(product={product!r}, '
                        f'role IN {ntype.default_roles}, is_active=True))'
                    )

            pref = _get_user_preference(user, key)
            if pref is None:
                self.stdout.write('    preference:      (none — registry defaults apply)')
            elif pref.is_muted:
                self.stdout.write(self.style.WARNING('    preference:      MUTED'))
            else:
                channels = []
                for ch in ('in_app', 'email', 'sms', 'boswell'):
                    enabled = getattr(pref, f'channel_{ch}', None)
                    if enabled is not None:
                        channels.append(f'{ch}={"on" if enabled else "off"}')
                self.stdout.write(f'    preference:      {" ".join(channels)}')

            if 'email' in ntype.default_channels and not getattr(user, 'email', None):
                self.stdout.write(self.style.ERROR(
                    '    ! email channel will fail: user has no email address'
                ))

    def _print_recent_logs(self, user):
        log_path = getattr(settings, 'KEEL_NOTIFICATION_LOG_MODEL', None)
        self.stdout.write(self.style.MIGRATE_LABEL('\nRecent NotificationLog entries (last 20):'))
        if not log_path:
            self.stdout.write('  (KEEL_NOTIFICATION_LOG_MODEL not configured)')
            return
        try:
            LogModel = apps.get_model(log_path)
        except Exception as e:
            self.stdout.write(f'  (could not load log model: {e})')
            return
        logs = LogModel.objects.filter(recipient=user).order_by('-id')[:20]
        if not logs:
            self.stdout.write('  (no log entries — notify() has never fired for this user)')
            return
        for entry in logs:
            ts = getattr(entry, 'created_at', None)
            ts_str = ts.strftime('%Y-%m-%d %H:%M') if ts else '?'
            status = self.style.SUCCESS('OK') if entry.success else self.style.ERROR('FAIL')
            err = f'  err={entry.error_message!r}' if entry.error_message else ''
            self.stdout.write(
                f'  {ts_str}  {entry.notification_type:<32} {entry.channel:<8} {status}{err}'
            )
