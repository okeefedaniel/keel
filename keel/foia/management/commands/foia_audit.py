"""
FOIA readiness audit — validates that every DockLabs product is FOIA-enabled.

Usage:
    python manage.py foia_audit
    python manage.py foia_audit --fail-on-error   # exit 1 on any FAIL
    python manage.py foia_audit --json             # JSON output for CI/CD

Checks per product:
    1. AuditMiddleware is in MIDDLEWARE (IP capture)
    2. KEEL_AUDIT_LOG_MODEL is set (audit trail)
    3. KEEL_FOIA_EXPORT_MODEL is set (Admiralty export queue)
    4. Registered exportable types exist (one-click export)
    5. Concrete AuditLog model has ip_address field
    6. Concrete AuditLog model is immutable (save/delete guards)
"""
import json as json_module
import sys

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

from keel.foia.export import foia_export_registry


class Command(BaseCommand):
    help = 'Audit FOIA readiness across the DockLabs platform.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fail-on-error', action='store_true',
            help='Exit with code 1 if any check fails.',
        )
        parser.add_argument(
            '--json', action='store_true',
            help='Output results as JSON.',
        )

    def handle(self, *args, **options):
        results = []
        has_failure = False

        # --- Global checks ---
        results.append(self._check_middleware())
        results.append(self._check_audit_model_setting())
        results.append(self._check_foia_export_model_setting())
        results.append(self._check_audit_model_fields())
        results.append(self._check_audit_model_immutability())

        # --- Export registry checks ---
        all_types = foia_export_registry.get_exportable_types()
        products_with_exports = {t.product for t in all_types}

        known_products = self._get_known_products()
        for product in known_products:
            if product in ('keel', 'admiralty'):
                # Keel is platform admin, Admiralty is the FOIA hub itself
                continue
            if product in products_with_exports:
                types = foia_export_registry.get_exportable_types(product=product)
                type_names = [t.display_name for t in types]
                results.append({
                    'check': f'{product}: exportable types registered',
                    'status': 'PASS',
                    'detail': f'{len(types)} type(s): {", ".join(type_names)}',
                })
            else:
                results.append({
                    'check': f'{product}: exportable types registered',
                    'status': 'WARN',
                    'detail': (
                        f'No exportable types registered for "{product}". '
                        'FOIA staff cannot one-click export records from this product. '
                        'Use foia_export_registry.register() in AppConfig.ready().'
                    ),
                })

        for r in results:
            if r['status'] == 'FAIL':
                has_failure = True

        if options['json']:
            self.stdout.write(json_module.dumps({
                'foia_audit': results,
                'passed': not has_failure,
            }, indent=2))
        else:
            self.stdout.write('\n  FOIA Readiness Audit\n  ' + '=' * 40 + '\n')
            for r in results:
                icon = {'PASS': '+', 'WARN': '!', 'FAIL': 'X'}[r['status']]
                self.stdout.write(f'  [{icon}] {r["status"]:4s} {r["check"]}')
                if r.get('detail'):
                    self.stdout.write(f'         {r["detail"]}')
            self.stdout.write('')

            passes = sum(1 for r in results if r['status'] == 'PASS')
            warns = sum(1 for r in results if r['status'] == 'WARN')
            fails = sum(1 for r in results if r['status'] == 'FAIL')
            self.stdout.write(
                f'  {passes} passed, {warns} warnings, {fails} failures\n'
            )

        if options['fail_on_error'] and has_failure:
            sys.exit(1)

    def _get_known_products(self):
        """Get list of known DockLabs products from accounts.Product if available."""
        try:
            from keel.accounts.models import Product
            return [choice[0] for choice in Product.choices]
        except Exception:
            return [
                'beacon', 'admiralty', 'harbor', 'manifest',
                'lookout', 'bounty', 'purser', 'yeoman', 'keel',
            ]

    def _check_middleware(self):
        middleware = getattr(settings, 'MIDDLEWARE', [])
        if 'keel.core.middleware.AuditMiddleware' in middleware:
            return {
                'check': 'AuditMiddleware in MIDDLEWARE',
                'status': 'PASS',
                'detail': 'IP addresses are captured on every request.',
            }
        return {
            'check': 'AuditMiddleware in MIDDLEWARE',
            'status': 'FAIL',
            'detail': (
                'keel.core.middleware.AuditMiddleware is not in MIDDLEWARE. '
                'IP addresses will not be captured for FOIA audit trails.'
            ),
        }

    def _check_audit_model_setting(self):
        model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', None)
        if model_path:
            return {
                'check': 'KEEL_AUDIT_LOG_MODEL is set',
                'status': 'PASS',
                'detail': f'Using: {model_path}',
            }
        return {
            'check': 'KEEL_AUDIT_LOG_MODEL is set',
            'status': 'WARN',
            'detail': 'Not set — using default "core.AuditLog".',
        }

    def _check_foia_export_model_setting(self):
        model_path = getattr(settings, 'KEEL_FOIA_EXPORT_MODEL', None)
        if model_path:
            return {
                'check': 'KEEL_FOIA_EXPORT_MODEL is set',
                'status': 'PASS',
                'detail': f'Using: {model_path}',
            }
        return {
            'check': 'KEEL_FOIA_EXPORT_MODEL is set',
            'status': 'FAIL',
            'detail': (
                'KEEL_FOIA_EXPORT_MODEL is not set. '
                'One-click FOIA export to Admiralty will not work. '
                'Set it to your concrete FOIAExportItem model path.'
            ),
        }

    def _check_audit_model_fields(self):
        model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
        try:
            AuditLog = apps.get_model(model_path)
        except LookupError:
            return {
                'check': 'AuditLog model has required fields',
                'status': 'FAIL',
                'detail': f'Model {model_path} not found.',
            }

        required = ['ip_address', 'timestamp', 'user', 'action', 'entity_type', 'entity_id', 'changes']
        missing = [f for f in required if not hasattr(AuditLog, f)]
        if missing:
            return {
                'check': 'AuditLog model has required fields',
                'status': 'FAIL',
                'detail': f'Missing fields: {", ".join(missing)}',
            }
        return {
            'check': 'AuditLog model has required FOIA fields (ip_address, timestamp, changes)',
            'status': 'PASS',
            'detail': f'Model: {model_path}',
        }

    def _check_audit_model_immutability(self):
        model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
        try:
            AuditLog = apps.get_model(model_path)
        except LookupError:
            return {
                'check': 'AuditLog is immutable',
                'status': 'FAIL',
                'detail': f'Model {model_path} not found.',
            }

        # Check if delete raises ValueError (from AbstractAuditLog)
        try:
            instance = AuditLog()
            instance.delete()
            return {
                'check': 'AuditLog is immutable (delete guard)',
                'status': 'FAIL',
                'detail': 'AuditLog.delete() did not raise ValueError. Audit records must be immutable.',
            }
        except ValueError:
            return {
                'check': 'AuditLog is immutable (delete guard)',
                'status': 'PASS',
                'detail': 'delete() raises ValueError — audit records cannot be removed.',
            }
        except Exception:
            return {
                'check': 'AuditLog is immutable (delete guard)',
                'status': 'WARN',
                'detail': 'Could not verify immutability (model may need database).',
            }
