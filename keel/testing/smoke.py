"""Smoke tests against live/local DockLabs deployments.

Tests every URL as every user type via Django's test Client. For each product:
1. Public pages load without errors
2. Each demo role can log in
3. Each demo role can access their permitted pages
4. No 500 errors anywhere
5. No placeholder href="#" links (excluding dropdowns)
6. 404s return 404 (not 500)
7. Health check and robots.txt work

Can run against:
- Local Django test Client (default, uses each product's DB)
- Live deployments via HTTP (with --live flag)
"""
import os
import re
import sys
import traceback

from .config import DEMO_PASSWORD, PRODUCTS
from .result import TestResult


def run_smoke_tests(T: TestResult, product_names=None, live=False):
    """Run smoke tests for all products.

    Args:
        T: TestResult accumulator.
        product_names: Optional list of product keys. Defaults to all.
        live: If True, test against live URLs via requests.
              If False, use Django test Client locally.
    """
    products = product_names or list(PRODUCTS.keys())

    for key in products:
        product = PRODUCTS[key]
        T.product(product.name)

        if live:
            _smoke_live(T, product)
        else:
            _smoke_local(T, product)


# ---------------------------------------------------------------------------
# Local smoke tests (Django test Client)
# ---------------------------------------------------------------------------

def _smoke_local(T, product):
    """Run smoke tests using Django's test Client against the local DB."""

    # Each product is a separate Django project, so we need to bootstrap it
    # in a subprocess. We generate a test script and run it.
    import json
    import subprocess
    import tempfile

    test_script = _generate_local_test_script(product)

    python = str(product.path / product.venv_python)
    if not os.path.exists(python):
        T.section('Setup')
        T.fail(f'Python not found: {python}')
        return

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, dir=str(product.path),
    ) as f:
        f.write(test_script)
        script_path = f.name

    try:
        result = subprocess.run(
            [python, script_path],
            cwd=str(product.path),
            capture_output=True,
            text=True,
            timeout=300,
            env={
                **dict(os.environ),
                'DJANGO_SETTINGS_MODULE': product.settings_module,
                'DJANGO_SECRET_KEY': 'nightly-test-key-not-for-production',
            },
        )

        # Parse JSON results from stdout
        output = result.stdout.strip()
        if output:
            try:
                results = json.loads(output)
                for r in results:
                    if r['passed']:
                        T.section(r['section'])
                        T.ok(r['label'], r.get('detail', ''))
                    else:
                        T.section(r['section'])
                        T.fail(r['label'], r.get('detail', ''))
            except json.JSONDecodeError:
                T.section('Smoke Tests')
                T.fail(
                    'Could not parse smoke test output',
                    output[:500],
                )

        if result.returncode != 0 and not output:
            T.section('Smoke Tests')
            T.fail(
                'Smoke test script failed',
                (result.stderr or '')[:500],
            )

    except subprocess.TimeoutExpired:
        T.section('Smoke Tests')
        T.fail('Smoke tests timed out', 'exceeded 300s')
    finally:
        os.unlink(script_path)


def _generate_local_test_script(product):
    """Generate a self-contained Python script that runs smoke tests.

    The script bootstraps Django, uses test Client, and outputs JSON results.
    """
    import json

    public_urls = json.dumps(product.public_urls)
    auth_urls = json.dumps(product.auth_urls)
    demo_roles = json.dumps(product.demo_roles)

    return f'''#!/usr/bin/env python
"""Auto-generated smoke test for {product.name}."""
import json
import os
import re
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{product.settings_module}')

import django
django.setup()

from django.conf import settings
from django.test import Client

if 'testserver' not in settings.ALLOWED_HOSTS and '*' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append('testserver')

DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo' + '2026!')
results = []


def ok(section, label, detail=''):
    results.append({{'section': section, 'label': label, 'passed': True, 'detail': detail}})


def fail(section, label, detail=''):
    results.append({{'section': section, 'label': label, 'passed': False, 'detail': detail}})


def check(section, condition, label, detail=''):
    if condition:
        ok(section, label, detail)
    else:
        fail(section, label, detail)


def check_response(section, client, url, label, allowed_codes=None):
    """GET a URL and check for success."""
    if allowed_codes is None:
        allowed_codes = {{200, 301, 302}}
    try:
        resp = client.get(url)
        passed = resp.status_code in allowed_codes
        is_500 = resp.status_code >= 500
        detail = f'status={{resp.status_code}}'

        if is_500:
            body = resp.content.decode()[:200]
            fail(section, f'{{label}} returned 500', f'{{detail}}: {{body}}')
        elif passed:
            ok(section, label, detail)
        else:
            fail(section, label, detail)

        return resp
    except Exception as e:
        fail(section, label, str(e)[:200])
        return None


def scan_broken_links(section, client, url, label):
    """Check a page for placeholder href="#" links."""
    try:
        resp = client.get(url, follow=True)
        if resp.status_code != 200:
            return
        body = resp.content.decode()
        bare_hash = body.count('href="#"')
        dropdowns = body.lower().count('dropdown-toggle')
        excess = max(0, bare_hash - dropdowns - 2)
        check(
            section, excess == 0,
            f'No placeholder links in {{label}}',
            f'{{bare_hash}} href="#", {{dropdowns}} dropdown-toggles',
        )
    except Exception:
        pass


# ── Health check ──
section = 'Health & Operations'
c = Client()
check_response(section, c, '/health/', 'Health check returns 200', {{200}})
check_response(section, c, '/robots.txt', 'robots.txt returns 200', {{200}})

# ── Public pages ──
section = 'Public Pages'
public_urls = {public_urls}
for url in public_urls:
    check_response(section, c, url, f'GET {{url}}')

# ── Demo role login & page access ──
demo_roles = {demo_roles}
auth_urls = {auth_urls}

for role in demo_roles:
    section = f'Role: {{role}}'
    rc = Client()
    login_ok = rc.login(username=role, password=DEMO_PASSWORD)
    check(section, login_ok, f'{{role}} can log in')

    if not login_ok:
        fail(section, f'Skipping {{role}} page tests — login failed')
        continue

    # Test all pages for this role
    role_urls = auth_urls.get(role, [])
    for url in role_urls:
        check_response(section, rc, url, f'{{role}}: GET {{url}}')

    # Scan key pages for broken links
    if role_urls:
        scan_broken_links(section, rc, role_urls[0], f'{{role}}: {{role_urls[0]}}')

# ── 404 handling ──
section = 'Error Handling'
import uuid
fake = str(uuid.uuid4())
resp = c.get(f'/nonexistent-{{fake}}/')
check(section, resp.status_code == 404, '404 on unknown URL', f'status={{resp.status_code}}')
check(section, resp.status_code < 500, 'Unknown URL is not a 500')

# ── Output ──
print(json.dumps(results))
'''


# ---------------------------------------------------------------------------
# Live smoke tests (HTTP requests against deployed products)
# ---------------------------------------------------------------------------

def _smoke_live(T, product):
    """Run smoke tests against the live deployment via HTTP."""
    try:
        import requests
    except ImportError:
        T.section('Setup')
        T.fail('requests package not installed — pip install requests')
        return

    base = product.live_url.rstrip('/')
    session = requests.Session()
    session.headers['User-Agent'] = 'DockLabs-Nightly-Tests/1.0'

    # Health check
    T.section('Health & Operations')
    try:
        resp = session.get(f'{base}/health/', timeout=15)
        T.check(resp.status_code == 200, 'Health check', f'status={resp.status_code}')
    except Exception as e:
        T.fail('Health check', str(e)[:200])
        return  # If health check fails, skip the rest

    # Robots.txt
    try:
        resp = session.get(f'{base}/robots.txt', timeout=10)
        T.check(resp.status_code == 200, 'robots.txt', f'status={resp.status_code}')
    except Exception as e:
        T.fail('robots.txt', str(e)[:200])

    # Public pages
    T.section('Public Pages')
    for url in product.public_urls:
        try:
            resp = session.get(f'{base}{url}', timeout=15, allow_redirects=True)
            T.check(
                resp.status_code < 500,
                f'GET {url}',
                f'status={resp.status_code}',
            )
        except Exception as e:
            T.fail(f'GET {url}', str(e)[:200])

    # Demo login for each role
    for role in product.demo_roles:
        T.section(f'Role: {role}')
        role_session = requests.Session()
        role_session.headers['User-Agent'] = 'DockLabs-Nightly-Tests/1.0'

        # Try demo login endpoint
        try:
            # Get CSRF token from login page
            login_page = role_session.get(
                f'{base}/auth/login/',
                timeout=15,
                allow_redirects=True,
            )
            csrf = _extract_csrf_from_html(login_page.text)

            # POST to demo login
            resp = role_session.post(
                f'{base}/demo-login/',
                data={'role': role, 'csrfmiddlewaretoken': csrf},
                headers={'Referer': f'{base}/auth/login/'},
                timeout=15,
                allow_redirects=True,
            )
            # Check we ended up on dashboard (login succeeded)
            logged_in = (
                resp.status_code == 200
                and '/login' not in resp.url
            )
            T.check(logged_in, f'{role} demo login', f'final_url={resp.url}')

            if not logged_in:
                continue

            # Test auth pages for this role
            role_urls = product.auth_urls.get(role, [])
            for url in role_urls:
                try:
                    resp = role_session.get(
                        f'{base}{url}',
                        timeout=15,
                        allow_redirects=True,
                    )
                    T.check(
                        resp.status_code < 500,
                        f'{role}: GET {url}',
                        f'status={resp.status_code}',
                    )
                except Exception as e:
                    T.fail(f'{role}: GET {url}', str(e)[:200])

        except Exception as e:
            T.fail(f'{role} demo login', str(e)[:200])


def _extract_csrf_from_html(html):
    """Extract CSRF token from HTML."""
    m = re.search(
        r'name=["\']csrfmiddlewaretoken["\'] value=["\']([^"\']+)["\']',
        html,
    )
    return m.group(1) if m else ''
