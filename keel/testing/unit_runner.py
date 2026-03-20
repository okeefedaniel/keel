"""Run each product's Django test suite via subprocess."""
import subprocess
import time

from .config import PRODUCTS
from .result import TestResult


def run_django_tests(T: TestResult, product_names=None):
    """Run `manage.py test` for each product.

    Args:
        T: TestResult accumulator.
        product_names: Optional list of product keys to test.
            Defaults to all products.
    """
    products = product_names or list(PRODUCTS.keys())
    # Deduplicate by repo_dir (beacon/admiralty share a repo)
    seen_dirs = set()

    for key in products:
        product = PRODUCTS[key]
        if not product.has_django_tests:
            continue

        repo_dir = str(product.path)
        settings = product.settings_module

        # Don't run tests twice for the same repo
        # (beacon and admiralty share a repo — run beacon's tests once)
        dedup_key = f'{repo_dir}:{settings}'
        if dedup_key in seen_dirs:
            continue
        seen_dirs.add(dedup_key)

        T.product(product.name)
        T.section('Django Unit Tests')

        python = str(product.path / product.venv_python)
        cmd = [
            python, 'manage.py', 'test',
            '--verbosity=2', '--no-input',
        ]
        env_extra = {
            'DJANGO_SETTINGS_MODULE': settings,
            'DJANGO_SECRET_KEY': 'nightly-test-key-not-for-production',
        }

        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min per product
                env={**dict(__import__('os').environ), **env_extra},
            )
            duration = time.time() - start
            output = result.stdout + result.stderr

            if result.returncode == 0:
                # Count tests from output
                T.ok(
                    f'{product.name} test suite passed',
                    f'{duration:.1f}s',
                )
            else:
                # Extract failure summary from output
                # Django test output ends with "FAILED (failures=N, errors=N)"
                summary = ''
                for line in output.splitlines()[-20:]:
                    if 'FAIL' in line or 'ERROR' in line or 'Traceback' in line:
                        summary += line + ' | '
                T.fail(
                    f'{product.name} test suite FAILED',
                    f'exit={result.returncode}, {duration:.1f}s. {summary[:300]}',
                )

                # Log individual failures
                _extract_test_failures(T, output)

        except subprocess.TimeoutExpired:
            T.fail(f'{product.name} test suite timed out', 'exceeded 600s')
        except FileNotFoundError:
            T.fail(
                f'{product.name} test suite could not run',
                f'Python not found: {python}',
            )


def _extract_test_failures(T: TestResult, output: str):
    """Parse Django test output to log individual failures."""
    in_failure = False
    current_test = ''

    for line in output.splitlines():
        if line.startswith('FAIL:') or line.startswith('ERROR:'):
            current_test = line
            in_failure = True
        elif in_failure and line.startswith('---'):
            in_failure = False
            if current_test:
                T.fail(f'  {current_test[:100]}')
                current_test = ''
