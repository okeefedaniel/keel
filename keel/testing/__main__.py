"""Entry point for the DockLabs nightly test suite.

Usage:
    # Run everything (unit tests + smoke tests + UI audit + security audit, all products)
    python -m keel.testing

    # Smoke tests only against local instances
    python -m keel.testing --smoke-only

    # Smoke tests against live deployments
    python -m keel.testing --smoke-only --live

    # Unit tests only
    python -m keel.testing --unit-only

    # UI consistency audit only
    python -m keel.testing --ui-only

    # Security audit only
    python -m keel.testing --security-only

    # Security audit with auto-fix
    python -m keel.testing --security-only --auto-fix

    # Specific products
    python -m keel.testing --products lookout harbor

    # JSON output (for CI/CD)
    python -m keel.testing --json

    # Generate failure prompt for Claude Code (auto-fix mode)
    python -m keel.testing --fix-prompt
"""
import argparse
import json as json_module
import sys

from .config import PRODUCTS
from .result import TestResult
from .security_audit import run_security_audit
from .smoke import run_smoke_tests
from .ui_audit import run_ui_audit
from .unit_runner import run_django_tests


def _notify_keel_dashboard(critical_findings):
    """Create ChangeRequests in the keel dashboard for critical findings.

    This is best-effort — if the DB isn't available, findings are logged to
    stderr instead.
    """
    if not critical_findings:
        return

    try:
        import django
        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'keel_site.settings')
        django.setup()

        from keel.requests.models import ChangeRequest

        for finding in critical_findings:
            # Avoid duplicates — check if an open request already exists
            existing = ChangeRequest.objects.filter(
                title__icontains=finding['finding'][:80],
                status__in=('pending', 'approved', 'implementing'),
            ).exists()
            if existing:
                continue

            ChangeRequest.objects.create(
                title=f"[SECURITY] {finding['finding'][:80]}",
                description=(
                    f"**Product:** {finding['product']}\n"
                    f"**Severity:** {finding['severity']}\n"
                    f"**Finding:** {finding['finding']}\n"
                    f"**Recommendation:** {finding['recommendation']}\n\n"
                    f"_Auto-reported by the nightly security audit._"
                ),
                product=_map_product_name(finding['product']),
                category='BUG',
                priority='CRITICAL' if finding['severity'] == 'CRITICAL' else 'HIGH',
            )
        print(
            f'\n{len(critical_findings)} critical finding(s) reported to Keel dashboard.',
            file=sys.stderr,
        )
    except Exception as e:
        print(f'\nCould not notify Keel dashboard: {e}', file=sys.stderr)
        print('Critical findings:', file=sys.stderr)
        for f in critical_findings:
            print(f"  [{f['severity']}] {f['product']}: {f['finding']}", file=sys.stderr)


def _map_product_name(name):
    """Map audit product name to ChangeRequest.Product choice."""
    mapping = {
        'Beacon': 'BEACON',
        'Harbor': 'HARBOR',
        'Lookout': 'LOOKOUT',
        'Keel': 'BEACON',  # Keel issues go to general
    }
    return mapping.get(name, 'BEACON')


def main():
    parser = argparse.ArgumentParser(
        description='DockLabs Nightly Test Suite',
    )
    parser.add_argument(
        '--products', nargs='+',
        choices=list(PRODUCTS.keys()),
        help='Products to test (default: all)',
    )
    parser.add_argument(
        '--smoke-only', action='store_true',
        help='Run only smoke tests (skip unit tests, UI audit, and security audit)',
    )
    parser.add_argument(
        '--unit-only', action='store_true',
        help='Run only Django unit tests (skip smoke tests, UI audit, and security audit)',
    )
    parser.add_argument(
        '--ui-only', action='store_true',
        help='Run only the UI consistency audit',
    )
    parser.add_argument(
        '--security-only', action='store_true',
        help='Run only the security audit',
    )
    parser.add_argument(
        '--auto-fix', action='store_true',
        help='Automatically fix safe security issues (e.g., missing settings)',
    )
    parser.add_argument(
        '--live', action='store_true',
        help='Run smoke tests against live deployments (*.docklabs.ai)',
    )
    parser.add_argument(
        '--json', action='store_true',
        help='Output JSON report instead of text',
    )
    parser.add_argument(
        '--fix-prompt', action='store_true',
        help='Output a Claude Code prompt for auto-fixing failures',
    )
    parser.add_argument(
        '--report-file',
        help='Write report to file (in addition to stdout)',
    )
    parser.add_argument(
        '--notify-dashboard', action='store_true',
        help='Report critical security findings to Keel dashboard as ChangeRequests',
    )

    args = parser.parse_args()

    T = TestResult()
    products = args.products
    critical_findings = []

    # --- Run tests ---

    if args.ui_only:
        run_ui_audit(T)
    elif args.security_only:
        critical_findings = run_security_audit(
            T, product_names=products, auto_fix=args.auto_fix,
        )
    else:
        if not args.smoke_only:
            run_django_tests(T, product_names=products)

        if not args.unit_only:
            run_smoke_tests(T, product_names=products, live=args.live)

        # UI audit runs as part of the full suite (unless --smoke-only or --unit-only)
        if not args.smoke_only and not args.unit_only:
            run_ui_audit(T)

        # Security audit runs as part of the full suite
        if not args.smoke_only and not args.unit_only:
            critical_findings = run_security_audit(
                T, product_names=products, auto_fix=args.auto_fix,
            )

    # --- Notify Keel dashboard of critical findings ---
    if critical_findings and (args.notify_dashboard or args.security_only):
        _notify_keel_dashboard(critical_findings)

    # --- Output ---

    if args.json:
        report = T.json_report()
    else:
        report = T.text_report()

    print(report)

    if args.report_file:
        with open(args.report_file, 'w') as f:
            f.write(report)

    if args.fix_prompt:
        prompt = T.failure_prompt()
        if prompt:
            # Write prompt to a file for the cron wrapper to pick up
            prompt_file = args.report_file.replace('.txt', '.prompt') if args.report_file else '/tmp/docklabs_fix_prompt.txt'
            with open(prompt_file, 'w') as f:
                f.write(prompt)
            print(f'\nFix prompt written to: {prompt_file}', file=sys.stderr)

    sys.exit(0 if T.failed == 0 else 1)


if __name__ == '__main__':
    main()
