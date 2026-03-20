"""
Management command to run Keel security compliance audit.

Usage:
    python manage.py security_audit
    python manage.py security_audit --json
    python manage.py security_audit --fail-on-error
"""
import json
import sys

from django.core.management.base import BaseCommand

from keel.security.compliance import run_security_audit, ComplianceCheck


class Command(BaseCommand):
    help = 'Run security compliance audit against Keel security standards'

    def add_arguments(self, parser):
        parser.add_argument(
            '--json', action='store_true',
            help='Output results as JSON',
        )
        parser.add_argument(
            '--fail-on-error', action='store_true',
            help='Exit with code 1 if any checks fail (for CI/CD)',
        )

    def handle(self, *args, **options):
        results = run_security_audit()

        if options['json']:
            data = {
                'checks': [
                    {
                        'name': r.name,
                        'status': r.status,
                        'message': r.message,
                        'category': r.category,
                    }
                    for r in results
                ],
                'summary': {
                    'total': len(results),
                    'passed': sum(1 for r in results if r.status == ComplianceCheck.PASS),
                    'failed': sum(1 for r in results if r.status == ComplianceCheck.FAIL),
                    'warnings': sum(1 for r in results if r.status == ComplianceCheck.WARN),
                },
            }
            self.stdout.write(json.dumps(data, indent=2))
        else:
            self.stdout.write('\n' + self.style.HTTP_INFO('=== DockLabs Security Audit ===') + '\n')

            categories = {}
            for r in results:
                categories.setdefault(r.category, []).append(r)

            for cat, checks in categories.items():
                self.stdout.write(f'\n{cat.upper() or "GENERAL"}:')
                for check in checks:
                    if check.status == ComplianceCheck.PASS:
                        self.stdout.write(f'  {self.style.SUCCESS("PASS")} {check.name}: {check.message}')
                    elif check.status == ComplianceCheck.FAIL:
                        self.stdout.write(f'  {self.style.ERROR("FAIL")} {check.name}: {check.message}')
                    else:
                        self.stdout.write(f'  {self.style.WARNING("WARN")} {check.name}: {check.message}')

            passed = sum(1 for r in results if r.status == ComplianceCheck.PASS)
            failed = sum(1 for r in results if r.status == ComplianceCheck.FAIL)
            warned = sum(1 for r in results if r.status == ComplianceCheck.WARN)

            self.stdout.write(f'\n{self.style.HTTP_INFO("Summary")}: '
                              f'{passed} passed, {failed} failed, {warned} warnings')

        if options['fail_on_error']:
            failures = sum(1 for r in results if r.status == ComplianceCheck.FAIL)
            if failures:
                sys.exit(1)
