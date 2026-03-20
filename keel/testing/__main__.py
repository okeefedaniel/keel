"""Entry point for the DockLabs nightly test suite.

Usage:
    # Run everything (unit tests + smoke tests, all products)
    python -m keel.testing

    # Smoke tests only against local instances
    python -m keel.testing --smoke-only

    # Smoke tests against live deployments
    python -m keel.testing --smoke-only --live

    # Unit tests only
    python -m keel.testing --unit-only

    # Specific products
    python -m keel.testing --products lookout harbor

    # JSON output (for CI/CD)
    python -m keel.testing --json

    # Generate failure prompt for Claude Code (auto-fix mode)
    python -m keel.testing --fix-prompt
"""
import argparse
import sys

from .config import PRODUCTS
from .result import TestResult
from .smoke import run_smoke_tests
from .unit_runner import run_django_tests


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
        help='Run only smoke tests (skip unit tests)',
    )
    parser.add_argument(
        '--unit-only', action='store_true',
        help='Run only Django unit tests (skip smoke tests)',
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

    args = parser.parse_args()

    T = TestResult()
    products = args.products

    # --- Run tests ---

    if not args.smoke_only:
        run_django_tests(T, product_names=products)

    if not args.unit_only:
        run_smoke_tests(T, product_names=products, live=args.live)

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
