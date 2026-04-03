"""Audit and validate the notification type registry.

Reports on:
  - Orphaned database overrides (keys not in registry)
  - Invalid roles (not in PRODUCT_ROLES)
  - Invalid channels
  - Role coverage gaps (roles with zero notification types)
  - Registry summary statistics

Usage:
    python manage.py sync_notification_catalog          # audit report
    python manage.py sync_notification_catalog --json   # machine-readable
    python manage.py sync_notification_catalog --fix    # clean up orphans
"""
import json as json_module

from django.core.management.base import BaseCommand

from keel.accounts.models import NotificationTypeOverride, get_product_roles
from keel.notifications.registry import get_all_types


VALID_CHANNELS = {'in_app', 'email', 'sms', 'boswell'}
VALID_PRIORITIES = {'low', 'medium', 'high', 'urgent'}


class Command(BaseCommand):
    help = 'Audit notification type registry against database overrides and role definitions.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output results as JSON.',
        )
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Remove orphaned database overrides.',
        )

    def handle(self, *args, **options):
        output_json = options['json']
        fix = options['fix']

        all_types = get_all_types()
        product_roles = get_product_roles()

        # Collect all valid role codes across all products
        all_valid_roles = set()
        for roles_list in product_roles.values():
            for code, _label in roles_list:
                all_valid_roles.add(code)
        # 'all' is a special role meaning all authenticated users
        all_valid_roles.add('all')

        # Collect all roles that appear in notification type definitions
        roles_with_notifications = set()
        for ntype in all_types.values():
            roles_with_notifications.update(ntype.default_roles)

        # --- Orphaned overrides ---
        db_overrides = list(NotificationTypeOverride.objects.all())
        override_keys = {o.key for o in db_overrides}
        registry_keys = set(all_types.keys())
        orphaned = override_keys - registry_keys

        # --- Invalid roles in notification types ---
        invalid_roles = []
        for key, ntype in sorted(all_types.items()):
            for role in ntype.default_roles:
                if role not in all_valid_roles:
                    invalid_roles.append({
                        'type': key,
                        'role': role,
                    })

        # --- Invalid channels ---
        invalid_channels = []
        for key, ntype in sorted(all_types.items()):
            for ch in ntype.default_channels:
                if ch not in VALID_CHANNELS:
                    invalid_channels.append({
                        'type': key,
                        'channel': ch,
                    })

        # --- Invalid priorities ---
        invalid_priorities = []
        for key, ntype in sorted(all_types.items()):
            if ntype.priority not in VALID_PRIORITIES:
                invalid_priorities.append({
                    'type': key,
                    'priority': ntype.priority,
                })

        # --- Role coverage gaps ---
        # Roles defined in PRODUCT_ROLES but receiving zero notifications
        roles_without_notifications = all_valid_roles - roles_with_notifications - {'all'}

        # --- Category summary ---
        categories = {}
        for ntype in all_types.values():
            categories.setdefault(ntype.category, []).append(ntype.key)

        # --- Channel stats ---
        channel_stats = {}
        for ntype in all_types.values():
            for ch in ntype.default_channels:
                channel_stats[ch] = channel_stats.get(ch, 0) + 1

        # --- Fix orphans ---
        fixed_count = 0
        if fix and orphaned:
            fixed_count = NotificationTypeOverride.objects.filter(
                key__in=orphaned,
            ).delete()[0]

        # --- Build report ---
        issues = []
        if orphaned:
            issues.append({
                'severity': 'warning',
                'issue': 'orphaned_overrides',
                'count': len(orphaned),
                'keys': sorted(orphaned),
                'fixed': fixed_count if fix else None,
            })
        if invalid_roles:
            issues.append({
                'severity': 'error',
                'issue': 'invalid_roles',
                'count': len(invalid_roles),
                'details': invalid_roles,
            })
        if invalid_channels:
            issues.append({
                'severity': 'error',
                'issue': 'invalid_channels',
                'count': len(invalid_channels),
                'details': invalid_channels,
            })
        if invalid_priorities:
            issues.append({
                'severity': 'error',
                'issue': 'invalid_priorities',
                'count': len(invalid_priorities),
                'details': invalid_priorities,
            })
        if roles_without_notifications:
            issues.append({
                'severity': 'info',
                'issue': 'roles_without_notifications',
                'count': len(roles_without_notifications),
                'roles': sorted(roles_without_notifications),
            })

        report = {
            'total_types': len(all_types),
            'total_categories': len(categories),
            'total_overrides': len(db_overrides),
            'channel_stats': channel_stats,
            'categories': {k: len(v) for k, v in sorted(categories.items())},
            'issues': issues,
            'issue_count': len(issues),
            'status': 'clean' if not issues else 'issues_found',
        }

        if output_json:
            self.stdout.write(json_module.dumps(report, indent=2))
            return

        # --- Human-readable output ---
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('=' * 60))
        self.stdout.write(self.style.HTTP_INFO('  Notification Catalog Sync Report'))
        self.stdout.write(self.style.HTTP_INFO('=' * 60))
        self.stdout.write('')

        self.stdout.write(f'  Registry types:    {len(all_types)}')
        self.stdout.write(f'  Categories:        {len(categories)}')
        self.stdout.write(f'  DB overrides:      {len(db_overrides)}')
        self.stdout.write(f'  Channel coverage:  {channel_stats}')
        self.stdout.write('')

        # Category breakdown
        self.stdout.write(self.style.HTTP_INFO('  Categories:'))
        for cat, keys in sorted(categories.items()):
            self.stdout.write(f'    {cat}: {len(keys)} types')
        self.stdout.write('')

        if not issues:
            self.stdout.write(self.style.SUCCESS('  All clear — no issues found.'))
            self.stdout.write('')
            return

        # Report issues
        for issue in issues:
            severity = issue['severity']
            style = (
                self.style.ERROR if severity == 'error'
                else self.style.WARNING if severity == 'warning'
                else self.style.NOTICE
            )

            if issue['issue'] == 'orphaned_overrides':
                self.stdout.write(style(
                    f'  [{severity.upper()}] {issue["count"]} orphaned override(s) '
                    f'in database:'
                ))
                for key in issue['keys']:
                    self.stdout.write(f'    - {key}')
                if fix:
                    self.stdout.write(self.style.SUCCESS(
                        f'    Cleaned up {fixed_count} orphaned override(s).'
                    ))
                else:
                    self.stdout.write(
                        '    Run with --fix to remove these.'
                    )

            elif issue['issue'] == 'invalid_roles':
                self.stdout.write(style(
                    f'  [{severity.upper()}] {issue["count"]} notification type(s) '
                    f'reference undefined roles:'
                ))
                for detail in issue['details']:
                    self.stdout.write(
                        f'    - {detail["type"]}: role "{detail["role"]}" '
                        f'not in PRODUCT_ROLES'
                    )

            elif issue['issue'] == 'invalid_channels':
                self.stdout.write(style(
                    f'  [{severity.upper()}] {issue["count"]} notification type(s) '
                    f'reference invalid channels:'
                ))
                for detail in issue['details']:
                    self.stdout.write(
                        f'    - {detail["type"]}: channel "{detail["channel"]}"'
                    )

            elif issue['issue'] == 'invalid_priorities':
                self.stdout.write(style(
                    f'  [{severity.upper()}] {issue["count"]} notification type(s) '
                    f'have invalid priorities:'
                ))
                for detail in issue['details']:
                    self.stdout.write(
                        f'    - {detail["type"]}: priority "{detail["priority"]}"'
                    )

            elif issue['issue'] == 'roles_without_notifications':
                self.stdout.write(style(
                    f'  [{severity.upper()}] {issue["count"]} role(s) defined in '
                    f'PRODUCT_ROLES receive zero notifications:'
                ))
                for role in issue['roles']:
                    self.stdout.write(f'    - {role}')

            self.stdout.write('')

        self.stdout.write(
            self.style.WARNING(f'  {len(issues)} issue(s) found.')
        )
        self.stdout.write('')
