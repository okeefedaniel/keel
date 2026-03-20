"""Test result accumulator and report generator."""
import json
from datetime import datetime, timezone


class TestResult:
    """Accumulates PASS/FAIL results across all products and generates reports."""

    def __init__(self):
        self.results = []
        self.current_product = ''
        self.current_section = ''
        self.start_time = datetime.now(timezone.utc)

    def product(self, name):
        self.current_product = name

    def section(self, title):
        self.current_section = title

    def ok(self, label, detail=''):
        self.results.append({
            'product': self.current_product,
            'section': self.current_section,
            'label': label,
            'passed': True,
            'detail': detail,
        })

    def fail(self, label, detail=''):
        self.results.append({
            'product': self.current_product,
            'section': self.current_section,
            'label': label,
            'passed': False,
            'detail': detail,
        })

    def check(self, condition, label, detail=''):
        if condition:
            self.ok(label, detail)
        else:
            self.fail(label, detail)

    @property
    def total(self):
        return len(self.results)

    @property
    def passed(self):
        return sum(1 for r in self.results if r['passed'])

    @property
    def failed(self):
        return self.total - self.passed

    @property
    def failures(self):
        return [r for r in self.results if not r['passed']]

    def failures_by_product(self):
        """Group failures by product."""
        by_product = {}
        for r in self.failures:
            by_product.setdefault(r['product'], []).append(r)
        return by_product

    def text_report(self):
        """Generate a human-readable text report."""
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.start_time).total_seconds()

        lines = []
        lines.append('')
        lines.append('=' * 78)
        lines.append('  DOCKLABS NIGHTLY TEST REPORT')
        lines.append(f'  {self.start_time.strftime("%Y-%m-%d %H:%M:%S UTC")}')
        lines.append(f'  Duration: {duration:.1f}s')
        lines.append('=' * 78)

        prev_product = ''
        prev_section = ''
        for r in self.results:
            if r['product'] != prev_product:
                lines.append(f'\n{"=" * 78}')
                lines.append(f'  {r["product"].upper()}')
                lines.append(f'{"=" * 78}')
                prev_product = r['product']
                prev_section = ''
            if r['section'] != prev_section:
                lines.append(f'\n--- {r["section"]} ---')
                prev_section = r['section']
            status = 'PASS' if r['passed'] else '** FAIL **'
            line = f'  [{status}] {r["label"]}'
            if r['detail']:
                line += f'  ({r["detail"]})'
            lines.append(line)

        lines.append('\n' + '=' * 78)

        # Per-product summary
        products = {}
        for r in self.results:
            p = r['product']
            products.setdefault(p, {'total': 0, 'passed': 0})
            products[p]['total'] += 1
            if r['passed']:
                products[p]['passed'] += 1

        for p, counts in products.items():
            failed = counts['total'] - counts['passed']
            status = 'OK' if failed == 0 else f'{failed} FAILURES'
            lines.append(f'  {p:<20} {counts["passed"]}/{counts["total"]} passed  [{status}]')

        lines.append(f'\n  TOTAL: {self.total}  |  PASSED: {self.passed}  |  FAILED: {self.failed}')
        if self.failed:
            lines.append('  STATUS: FAILURES DETECTED')
        else:
            lines.append('  STATUS: ALL TESTS PASSED')
        lines.append('=' * 78)
        lines.append('')

        return '\n'.join(lines)

    def json_report(self):
        """Generate a JSON report for machine consumption."""
        end_time = datetime.now(timezone.utc)
        return json.dumps({
            'start_time': self.start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'duration_seconds': (end_time - self.start_time).total_seconds(),
            'total': self.total,
            'passed': self.passed,
            'failed': self.failed,
            'results': self.results,
            'failures': self.failures,
        }, indent=2)

    def failure_prompt(self):
        """Generate a Claude Code prompt describing the failures for auto-fix.

        Returns None if no failures.
        """
        if not self.failures:
            return None

        by_product = self.failures_by_product()
        lines = [
            'The DockLabs nightly test suite found failures. '
            'Investigate each failure, identify the root cause, and fix it. '
            'Run the product\'s test suite after fixing to verify.\n',
        ]

        for product, failures in by_product.items():
            lines.append(f'## {product}')
            for f in failures:
                lines.append(f'- [{f["section"]}] {f["label"]}')
                if f['detail']:
                    lines.append(f'  Detail: {f["detail"]}')
            lines.append('')

        lines.append(
            'For each failure:\n'
            '1. Read the relevant code to understand the issue\n'
            '2. Fix the root cause (not just the symptom)\n'
            '3. Run `python manage.py test` to verify\n'
            '4. Commit the fix with a descriptive message\n'
        )

        return '\n'.join(lines)
