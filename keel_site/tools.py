"""Tools views — run test suites and UI audits from the Keel admin console.

These run `python -m keel.testing` as a subprocess and stream results back.
On Railway (production), the test/audit code runs inside the container.
Locally, it runs against the local repos.
"""
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

# In-memory store for run results (resets on deploy — fine for an admin tool)
_runs = {}

PYTHON = sys.executable


def _admin_check(user):
    if user.is_superuser:
        return True
    try:
        from keel.accounts.models import ProductAccess
        return ProductAccess.objects.filter(
            user=user, role__in=('admin', 'system_admin'), is_active=True,
        ).exists()
    except Exception:
        return False


def admin_required(view_func):
    from functools import wraps

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        from django.core.exceptions import PermissionDenied
        if not _admin_check(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


@admin_required
def tools_dashboard(request):
    """Tools landing page — launch tests and UI audits."""
    recent_runs = sorted(_runs.values(), key=lambda r: r['started_at'], reverse=True)[:20]
    return render(request, 'tools/dashboard.html', {'recent_runs': recent_runs})


@admin_required
@require_POST
def run_tool(request):
    """Launch a test/audit run. Returns a run ID to poll for results."""
    # These tools require access to the product repos on the filesystem.
    # On Railway, only the keel repo is available.
    is_railway = bool(os.environ.get('RAILWAY_ENVIRONMENT'))
    tool = request.POST.get('tool', 'full')

    # Security audit + compliance check can run on Railway (no repo scanning needed)
    repo_tools = {'ui-audit', 'smoke', 'unit', 'full'}
    if is_railway and tool in repo_tools:
        return JsonResponse({
            'id': str(uuid.uuid4())[:8],
            'tool': tool,
            'products': ['all'],
            'status': 'error',
            'started_at': datetime.now().isoformat(),
            'finished_at': datetime.now().isoformat(),
            'output': (
                'This tool requires access to the product source code '
                '(beacon, harbor, lookout repos) which are not available on Railway.\n\n'
                'Run it locally instead:\n'
                '  cd ~/SynologyDrive/Work/CT/Web/keel\n'
                '  source .venv/bin/activate\n'
                f'  python -m keel.testing --{"ui-only" if tool == "ui-audit" else tool}'
            ),
            'report': None,
            'exit_code': 1,
            'started_by': str(request.user),
        })

    products = request.POST.getlist('products')

    cmd = [PYTHON, '-m', 'keel.testing', '--json']

    if tool == 'ui-audit':
        cmd.append('--ui-only')
    elif tool == 'smoke':
        cmd.append('--smoke-only')
    elif tool == 'smoke-live':
        cmd.extend(['--smoke-only', '--live'])
    elif tool == 'unit':
        cmd.append('--unit-only')
    elif tool == 'security':
        cmd.extend(['--security-only', '--notify-dashboard'])
    elif tool == 'security-fix':
        cmd.extend(['--security-only', '--auto-fix', '--notify-dashboard'])
    elif tool in ('notification-sync', 'notification-fix'):
        cmd = [PYTHON, 'manage.py', 'sync_notification_catalog', '--json']
        if tool == 'notification-fix':
            cmd.append('--fix')
    # else: full suite

    if products:
        cmd.extend(['--products'] + products)

    run_id = str(uuid.uuid4())[:8]
    _runs[run_id] = {
        'id': run_id,
        'tool': tool,
        'products': products or ['all'],
        'status': 'running',
        'started_at': datetime.now().isoformat(),
        'finished_at': None,
        'output': None,
        'report': None,
        'exit_code': None,
        'started_by': str(request.user),
    }

    # Run synchronously (tests are typically fast, and this is an admin tool)
    # For longer runs, we could use threading — but keep it simple for now.
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute max
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        _runs[run_id]['exit_code'] = result.returncode
        _runs[run_id]['status'] = 'passed' if result.returncode == 0 else 'failed'
        _runs[run_id]['output'] = result.stdout or result.stderr

        # Try to parse JSON output
        try:
            _runs[run_id]['report'] = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            _runs[run_id]['report'] = None

    except subprocess.TimeoutExpired:
        _runs[run_id]['status'] = 'timeout'
        _runs[run_id]['output'] = 'Run timed out after 10 minutes.'
    except Exception as e:
        _runs[run_id]['status'] = 'error'
        _runs[run_id]['output'] = str(e)

    _runs[run_id]['finished_at'] = datetime.now().isoformat()

    return JsonResponse(_runs[run_id])


@admin_required
def run_detail(request, run_id):
    """Get details of a specific run."""
    run = _runs.get(run_id)
    if not run:
        return JsonResponse({'error': 'Run not found'}, status=404)
    return JsonResponse(run)
