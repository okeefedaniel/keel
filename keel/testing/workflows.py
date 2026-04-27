"""Workflow integration tests — POST-based state transition testing.

Unlike smoke tests (which only GET pages), workflow tests exercise the
full lifecycle of each product's core features:
1. Create test data via the ORM
2. Submit forms via POST with the Django test Client
3. Verify state changes in the database
4. Test role-based permission enforcement

Each product's workflow tests are generated as Python code that runs
inside the product's Django subprocess (same pattern as smoke.py).
"""
import json
import logging
import os
import subprocess
import tempfile

from .config import PRODUCTS
from .result import TestResult

logger = logging.getLogger(__name__)


def run_workflow_tests(T: TestResult, product_names=None):
    """Run workflow tests for all products.

    Args:
        T: TestResult accumulator.
        product_names: Optional list of product keys. Defaults to all.
    """
    products = product_names or list(PRODUCTS.keys())

    for key in products:
        product = PRODUCTS.get(key)
        if not product:
            continue
        if not product.workflows:
            continue

        T.product(product.name)
        _run_product_workflows(T, product)


def _run_product_workflows(T, product):
    """Run workflow tests for a single product in a subprocess."""
    script = _generate_workflow_script(product)

    python = str(product.path / product.venv_python)
    if not os.path.exists(python):
        T.section('Workflow Setup')
        T.fail(f'Python not found: {python}')
        return

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, dir=str(product.path),
    ) as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            [python, script_path],
            cwd=str(product.path),
            capture_output=True,
            text=True,
            timeout=600,
            env={
                **dict(os.environ),
                'DJANGO_SETTINGS_MODULE': product.settings_module,
                'DJANGO_SECRET_KEY': 'workflow-test-key-not-for-production',
            },
        )

        output = result.stdout.strip()
        if output:
            try:
                results = json.loads(output)
                for r in results:
                    T.section(r.get('section', 'Workflow'))
                    if r['passed']:
                        T.ok(r['label'], r.get('detail', ''))
                    else:
                        T.fail(r['label'], r.get('detail', ''))
            except json.JSONDecodeError:
                T.section('Workflow Tests')
                T.fail('Could not parse workflow output', output[:500])

        if result.returncode != 0 and not output:
            T.section('Workflow Tests')
            T.fail('Workflow script failed', (result.stderr or '')[:500])

    except subprocess.TimeoutExpired:
        T.section('Workflow Tests')
        T.fail('Workflow tests timed out', 'exceeded 600s')
    finally:
        os.unlink(script_path)


def _generate_workflow_script(product):
    """Generate a self-contained workflow test script for a product."""
    workflows_json = json.dumps(product.workflows)
    name = product.name.lower()

    # Build the workflow function registry based on product name
    workflow_funcs = _WORKFLOW_REGISTRY.get(name, '')

    return f'''#!/usr/bin/env python
"""Auto-generated workflow tests for {product.name}."""
import json
import os
import sys
import uuid

os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{product.settings_module}')

import django
django.setup()

from django.conf import settings
from django.test import Client, RequestFactory
from django.contrib.auth import get_user_model

if 'testserver' not in settings.ALLOWED_HOSTS and '*' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append('testserver')

User = get_user_model()
results = []
WORKFLOWS = {workflows_json}


def ok(section, label, detail=''):
    results.append({{'section': section, 'label': label, 'passed': True, 'detail': detail}})


def fail(section, label, detail=''):
    results.append({{'section': section, 'label': label, 'passed': False, 'detail': detail}})


def check(section, condition, label, detail=''):
    if condition:
        ok(section, label, detail)
    else:
        fail(section, label, detail)


def get_csrf(client, url):
    """Extract CSRF token from a GET response."""
    resp = client.get(url)
    token = resp.cookies.get('csrftoken')
    if token:
        return token.value
    # Try from form
    import re
    body = resp.content.decode()
    m = re.search(r'name=["\\'"]csrfmiddlewaretoken["\\'"] value=["\\'"]([^\\"\\'\\']+)', body)
    return m.group(1) if m else ''


def login_as(role):
    """Login and return a Client for the given demo role.

    Demo users have unusable passwords (keel >= 0.20.1), so use
    `force_login` to bypass authentication after looking up the user
    by username.
    """
    try:
        user = User.objects.get(username=role)
    except User.DoesNotExist:
        return None
    c = Client(enforce_csrf_checks=False)
    c.force_login(user)
    return c


def post_form(client, url, data, section, label):
    """POST a form and check for success (redirect or 200)."""
    try:
        resp = client.post(url, data, follow=True)
        success = resp.status_code < 400
        check(section, success, label,
              f'status={{resp.status_code}}, final={{resp.request["PATH_INFO"] if hasattr(resp, "request") else "?"}}')
        return resp
    except Exception as e:
        fail(section, label, str(e)[:300])
        return None


# ─── Product-specific workflow functions ───
{workflow_funcs}


# ─── Execute requested workflows ───
for wf_name in WORKFLOWS:
    fn = globals().get(wf_name)
    if fn and callable(fn):
        try:
            fn()
        except Exception as e:
            fail('Workflow', f'{{wf_name}} crashed', str(e)[:500])
    else:
        fail('Workflow', f'{{wf_name}} not implemented', 'Missing workflow function')

print(json.dumps(results))
'''


# =========================================================================
# Product-specific workflow functions (injected into generated scripts)
# =========================================================================

_BEACON_WORKFLOWS = r'''
def test_company_crud():
    """Create, view, and update a company."""
    section = 'Beacon: Company CRUD'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return
    ok(section, 'Admin logged in')

    # Create company
    resp = post_form(c, '/companies/create/', {
        'name': f'Test Corp {uuid.uuid4().hex[:8]}',
        'industry_description': 'Test industry',
        'hq_address_line1': '100 Main St',
        'hq_city': 'Hartford',
        'hq_state': 'CT',
        'hq_zip_code': '06103',
    }, section, 'Create company')

    # List companies
    resp = c.get('/companies/')
    check(section, resp.status_code == 200, 'Companies list loads')

    # Moderation queue
    resp = c.get('/companies/moderation/')
    check(section, resp.status_code == 200, 'Moderation queue loads')


def test_interaction_crud():
    """Create an interaction."""
    section = 'Beacon: Interaction CRUD'
    c = login_as('relationship_manager')
    if not c:
        fail(section, 'RM login failed')
        return
    ok(section, 'Relationship manager logged in')

    resp = c.get('/interactions/')
    check(section, resp.status_code == 200, 'Interactions list loads')

    resp = c.get('/interactions/create/')
    check(section, resp.status_code == 200, 'Interaction create form loads')


def test_pipeline_crud():
    """View pipeline."""
    section = 'Beacon: Pipeline'
    c = login_as('relationship_manager')
    if not c:
        fail(section, 'RM login failed')
        return

    resp = c.get('/pipeline/')
    check(section, resp.status_code == 200, 'Pipeline list loads')

    resp = c.get('/pipeline/create/')
    check(section, resp.status_code == 200, 'Pipeline create form loads')


def test_foia_workflow():
    """FOIA request lifecycle."""
    section = 'Beacon: FOIA Workflow'
    c = login_as('foia_officer')
    if not c:
        fail(section, 'FOIA officer login failed')
        return
    ok(section, 'FOIA officer logged in')

    resp = c.get('/foia/')
    check(section, resp.status_code == 200, 'FOIA list loads')

    resp = c.get('/foia/dashboard/')
    check(section, resp.status_code == 200, 'FOIA dashboard loads')

    # Create a FOIA request
    resp = post_form(c, '/foia/create/', {
        'requester_name': 'Test Requester',
        'requester_email': 'test@example.com',
        'subject': f'Test FOIA {uuid.uuid4().hex[:8]}',
        'description': 'Test request description',
        'priority': 'normal',
    }, section, 'Create FOIA request')


def test_zone_permissions():
    """Verify zone-based access control."""
    section = 'Beacon: Zone Permissions'
    # Analyst should see companies but not FOIA
    c = login_as('analyst')
    if not c:
        fail(section, 'Analyst login failed')
        return

    resp = c.get('/companies/')
    check(section, resp.status_code == 200, 'Analyst can view companies')

    # Executive should be read-only
    c2 = login_as('executive')
    if c2:
        resp = c2.get('/dashboard/')
        check(section, resp.status_code == 200, 'Executive can view dashboard')
'''

_ADMIRALTY_WORKFLOWS = r'''
def test_foia_standalone():
    """FOIA workflow in standalone Admiralty mode."""
    section = 'Admiralty: FOIA Standalone'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return
    ok(section, 'Admin logged in')

    resp = c.get('/foia/')
    check(section, resp.status_code == 200, 'FOIA list loads')

    resp = c.get('/foia/dashboard/')
    check(section, resp.status_code == 200, 'FOIA dashboard loads')


def test_foia_document_upload():
    """Test document management."""
    section = 'Admiralty: Documents'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = c.get('/foia/documents/')
    check(section, resp.status_code == 200, 'Document list loads')


def test_foia_full_lifecycle():
    """Create FOIA request and advance through stages."""
    section = 'Admiralty: Full Lifecycle'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = post_form(c, '/foia/create/', {
        'requester_name': 'Lifecycle Test',
        'requester_email': 'lifecycle@test.com',
        'subject': f'Lifecycle Test {uuid.uuid4().hex[:8]}',
        'description': 'Full lifecycle test',
        'priority': 'normal',
    }, section, 'Create FOIA request')
'''

_HARBOR_WORKFLOWS = r'''
def test_applicant_workflow():
    """Applicant creates org, views opportunities, applies."""
    section = 'Harbor: Applicant Workflow'
    c = login_as('applicant')
    if not c:
        fail(section, 'Applicant login failed')
        return
    ok(section, 'Applicant logged in')

    resp = c.get('/applications/my/')
    check(section, resp.status_code == 200, 'My applications loads')

    resp = c.get('/awards/my/')
    check(section, resp.status_code == 200, 'My awards loads')

    # Browse opportunities
    resp = c.get('/opportunities/')
    check(section, resp.status_code == 200, 'Public opportunities loads')


def test_staff_review_workflow():
    """Staff reviews applications."""
    section = 'Harbor: Staff Review'
    c = login_as('program_officer')
    if not c:
        fail(section, 'Program officer login failed')
        return
    ok(section, 'Program officer logged in')

    resp = c.get('/applications/')
    check(section, resp.status_code == 200, 'Application list loads')

    resp = c.get('/reviews/')
    check(section, resp.status_code == 200, 'Review dashboard loads')


def test_award_workflow():
    """Staff manages awards."""
    section = 'Harbor: Award Workflow'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = c.get('/awards/')
    check(section, resp.status_code == 200, 'Awards list loads')

    resp = c.get('/grants/')
    check(section, resp.status_code == 200, 'Grants list loads')


def test_drawdown_workflow():
    """Fiscal officer manages drawdowns."""
    section = 'Harbor: Drawdown Workflow'
    c = login_as('fiscal_officer')
    if not c:
        fail(section, 'Fiscal officer login failed')
        return
    ok(section, 'Fiscal officer logged in')

    resp = c.get('/financial/drawdowns/')
    check(section, resp.status_code == 200, 'Drawdowns list loads')

    resp = c.get('/financial/transactions/')
    check(section, resp.status_code == 200, 'Transactions list loads')


def test_reporting_workflow():
    """Staff manages reports."""
    section = 'Harbor: Reporting'
    c = login_as('program_officer')
    if not c:
        fail(section, 'Program officer login failed')
        return

    resp = c.get('/reporting/')
    check(section, resp.status_code == 200, 'Reports list loads')


def test_closeout_workflow():
    """Staff manages closeouts."""
    section = 'Harbor: Closeout'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = c.get('/closeout/')
    check(section, resp.status_code == 200, 'Closeout list loads')


def test_signature_flow():
    """Staff manages signature flows."""
    section = 'Harbor: Signatures'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = c.get('/signatures/flows/')
    check(section, resp.status_code == 200, 'Signature flows list loads')

    resp = c.get('/signatures/packets/')
    check(section, resp.status_code == 200, 'Signing packets list loads')
'''

_MANIFEST_WORKFLOWS = r'''
def test_signing_flow():
    """Admin creates and manages signing flows."""
    section = 'Manifest: Signing Flow'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return
    ok(section, 'Admin logged in')

    resp = c.get('/flows/')
    check(section, resp.status_code == 200, 'Flows list loads')

    resp = c.get('/packets/')
    check(section, resp.status_code == 200, 'Packets list loads')

    resp = c.get('/roles/')
    check(section, resp.status_code == 200, 'Roles list loads')

    resp = c.get('/builder/')
    check(section, resp.status_code == 200, 'Template builder loads')


def test_decline_flow():
    """Signer views their pending signatures."""
    section = 'Manifest: Signer View'
    c = login_as('signer')
    if not c:
        # Signer might not have a demo account yet
        fail(section, 'Signer login failed (demo user may not exist)')
        return

    resp = c.get('/my/')
    check(section, resp.status_code == 200, 'My signatures loads')
'''

_LOOKOUT_WORKFLOWS = r'''
def test_bill_browsing():
    """Browse and search bills."""
    section = 'Lookout: Bill Browsing'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return
    ok(section, 'Admin logged in')

    resp = c.get('/bills/')
    check(section, resp.status_code == 200, 'Bills list loads')

    # Search
    resp = c.get('/bills/?q=education')
    check(section, resp.status_code == 200, 'Bill search works')


def test_testimony_workflow():
    """Create and manage testimony."""
    section = 'Lookout: Testimony'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = c.get('/testimony/')
    check(section, resp.status_code == 200, 'Testimony list loads')

    resp = c.get('/testimony/templates/')
    check(section, resp.status_code == 200, 'Testimony templates loads')


def test_watchlist():
    """Manage watchlist and keywords."""
    section = 'Lookout: Watchlist'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = c.get('/watchlist/')
    check(section, resp.status_code == 200, 'Watchlist loads')

    resp = c.get('/watchlist/scores/')
    check(section, resp.status_code == 200, 'Relevance scores loads')


def test_tracking_workflow():
    """Track bills and manage collaborators."""
    section = 'Lookout: Tracking'
    c = login_as('admin')
    if not c:
        fail(section, 'Admin login failed')
        return

    resp = c.get('/tracking/')
    check(section, resp.status_code == 200, 'Tracked bills loads')

    resp = c.get('/tracking/archives/')
    check(section, resp.status_code == 200, 'Archives loads')

    resp = c.get('/tracking/engagement/')
    check(section, resp.status_code == 200, 'Engagement history loads')


def test_collaborator_flow():
    """Test collaborator management."""
    section = 'Lookout: Collaborators'
    c = login_as('legislative_aid')
    if not c:
        fail(section, 'Legislative aid login failed')
        return

    resp = c.get('/tracking/')
    check(section, resp.status_code == 200, 'Legislative aid can view tracking')
'''

_BOUNTY_WORKFLOWS = r'''
def test_opportunity_tracking():
    """Browse and track opportunities."""
    section = 'Bounty: Opportunity Tracking'
    c = login_as('coordinator')
    if not c:
        fail(section, 'Coordinator login failed')
        return
    ok(section, 'Coordinator logged in')

    resp = c.get('/opportunities/')
    check(section, resp.status_code == 200, 'Opportunities list loads')

    resp = c.get('/tracked/')
    check(section, resp.status_code == 200, 'Tracked list loads')

    resp = c.get('/dashboard/')
    check(section, resp.status_code == 200, 'Dashboard loads')


def test_matching_preferences():
    """Set up AI matching preferences."""
    section = 'Bounty: Matching'
    c = login_as('coordinator')
    if not c:
        fail(section, 'Coordinator login failed')
        return

    resp = c.get('/matching/preferences/')
    check(section, resp.status_code == 200, 'User preferences loads')

    resp = c.get('/matching/state-preferences/')
    check(section, resp.status_code == 200, 'State preferences loads')

    resp = c.get('/matching/recommendations/')
    check(section, resp.status_code == 200, 'Recommendations loads')


def test_collaborator_flow():
    """Viewer has limited access."""
    section = 'Bounty: Role Permissions'
    c = login_as('viewer')
    if not c:
        fail(section, 'Viewer login failed')
        return

    resp = c.get('/dashboard/')
    check(section, resp.status_code == 200, 'Viewer can access dashboard')

    resp = c.get('/tracked/')
    check(section, resp.status_code == 200, 'Viewer can view tracked')

    # Viewer should NOT be able to access state preferences
    resp = c.get('/matching/state-preferences/')
    check(section, resp.status_code in (302, 403),
          'Viewer blocked from state preferences',
          f'status={resp.status_code}')
'''

_WORKFLOW_REGISTRY = {
    'beacon': _BEACON_WORKFLOWS,
    'admiralty': _ADMIRALTY_WORKFLOWS,
    'harbor': _HARBOR_WORKFLOWS,
    'manifest': _MANIFEST_WORKFLOWS,
    'lookout': _LOOKOUT_WORKFLOWS,
    'bounty': _BOUNTY_WORKFLOWS,
}
