"""
Keel shared demo login — one-click demo authentication for DockLabs products.

Usage in each product:

    # urls.py
    from keel.core.demo import demo_login_view
    urlpatterns = [
        path('demo-login/', demo_login_view, name='demo_login'),
    ]

    # In your login template, include the one-click buttons:
    {% load keel_demo %}
    {% demo_login_buttons %}

Configuration:
    DEMO_MODE = True                    # enable demo features
    DEMO_ROLES = ['admin', 'analyst']   # roles to show buttons for
    LOGIN_REDIRECT_URL = '/dashboard/'  # where to go after login

Convention:
    Username = role name (e.g., 'admin', 'legislative_aid')
    Password = DEMO_PASSWORD env var (all accounts)
"""
import os

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .utils import rate_limit


def _wants_json(request):
    accept = request.META.get('HTTP_ACCEPT', '')
    return 'application/json' in accept and 'text/html' not in accept


def _error(request, message, status, login_url='/accounts/login/'):
    if _wants_json(request):
        return JsonResponse({'error': message}, status=status)
    messages.error(request, message)
    return redirect(login_url)

DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo2026!')

# Display labels and icons for common roles across DockLabs products.
# Roles missing from this dict still work — get_role_display() generates
# a sensible default — but explicit entries give nicer icons and colors.
ROLE_DISPLAY = {
    # Shared / cross-product
    'admin': {'label': 'Admin', 'icon': 'bi-shield-check', 'color': 'danger'},
    'system_admin': {'label': 'System Admin', 'icon': 'bi-shield-lock', 'color': 'danger'},
    'agency_admin': {'label': 'Agency Admin', 'icon': 'bi-building-gear', 'color': 'warning'},
    # Beacon
    'relationship_manager': {'label': 'Relationship Manager', 'icon': 'bi-person-lines-fill', 'color': 'primary'},
    'foia_attorney': {'label': 'FOIA Attorney', 'icon': 'bi-briefcase', 'color': 'warning'},
    'analyst': {'label': 'Analyst', 'icon': 'bi-graph-up', 'color': 'info'},
    'executive': {'label': 'Executive', 'icon': 'bi-bar-chart-line', 'color': 'secondary'},
    'act_admin': {'label': 'AdvanceCT Admin', 'icon': 'bi-shield-check', 'color': 'danger'},
    'act_relationship_mgr': {'label': 'AdvanceCT RM', 'icon': 'bi-person-lines-fill', 'color': 'primary'},
    'act_analyst': {'label': 'AdvanceCT Analyst', 'icon': 'bi-graph-up', 'color': 'info'},
    'quasi_rm': {'label': 'Quasi RM', 'icon': 'bi-building', 'color': 'secondary'},
    # Admiralty
    'foia_manager': {'label': 'FOIA Manager', 'icon': 'bi-folder2-open', 'color': 'warning'},
    'foia_officer': {'label': 'FOIA Officer', 'icon': 'bi-file-earmark-text', 'color': 'primary'},
    # Harbor
    'program_officer': {'label': 'Program Officer', 'icon': 'bi-clipboard-data', 'color': 'primary'},
    'fiscal_officer': {'label': 'Fiscal Officer', 'icon': 'bi-cash-stack', 'color': 'success'},
    'federal_fund_coordinator': {'label': 'Federal Fund Coordinator', 'icon': 'bi-bank', 'color': 'primary'},
    'grants_manager': {'label': 'Grants Manager', 'icon': 'bi-cash-stack', 'color': 'success'},
    'reviewer': {'label': 'Reviewer', 'icon': 'bi-clipboard-check', 'color': 'info'},
    'applicant': {'label': 'Applicant', 'icon': 'bi-person-raised-hand', 'color': 'secondary'},
    'auditor': {'label': 'Auditor', 'icon': 'bi-search', 'color': 'warning'},
    # Lookout
    'legislative_aid': {'label': 'Legislative Aid', 'icon': 'bi-person-badge', 'color': 'primary'},
    'stakeholder': {'label': 'Stakeholder', 'icon': 'bi-people', 'color': 'info'},
    # Manifest
    'staff': {'label': 'Staff', 'icon': 'bi-person', 'color': 'primary'},
    'signer': {'label': 'Signer', 'icon': 'bi-pen', 'color': 'primary'},
    # Bounty
    'coordinator': {'label': 'Coordinator', 'icon': 'bi-diagram-3', 'color': 'primary'},
    'viewer': {'label': 'Viewer', 'icon': 'bi-eye', 'color': 'secondary'},
    # Purser
    'purser_admin': {'label': 'Admin', 'icon': 'bi-shield-check', 'color': 'danger'},
    'purser_submitter': {'label': 'Submitter', 'icon': 'bi-upload', 'color': 'primary'},
    'purser_reviewer': {'label': 'Reviewer', 'icon': 'bi-clipboard-check', 'color': 'info'},
    'purser_compliance_officer': {'label': 'Compliance Officer', 'icon': 'bi-check2-square', 'color': 'warning'},
    'purser_readonly': {'label': 'Read-Only', 'icon': 'bi-eye', 'color': 'secondary'},
    'external_submitter': {'label': 'External Submitter', 'icon': 'bi-box-arrow-in-right', 'color': 'secondary'},
    # Yeoman
    'yeoman_admin': {'label': 'Admin', 'icon': 'bi-shield-check', 'color': 'danger'},
    'yeoman_scheduler': {'label': 'Scheduler', 'icon': 'bi-calendar-check', 'color': 'primary'},
    'yeoman_viewer': {'label': 'Viewer', 'icon': 'bi-eye', 'color': 'info'},
    'yeoman_delegate': {'label': 'Delegate', 'icon': 'bi-person-check', 'color': 'success'},
    # Helm
    'helm_admin': {'label': 'Admin', 'icon': 'bi-shield-check', 'color': 'danger'},
    'helm_director': {'label': 'Director', 'icon': 'bi-compass', 'color': 'primary'},
    'helm_viewer': {'label': 'Viewer', 'icon': 'bi-eye', 'color': 'info'},
}


def get_demo_roles():
    """Return the list of demo roles configured for this product.

    Falls back to PRODUCT_ROLES for the current KEEL_PRODUCT_NAME when
    DEMO_ROLES is not explicitly set, so products don't need to duplicate
    their role list.
    """
    explicit = getattr(settings, 'DEMO_ROLES', None)
    if explicit is not None:
        return explicit

    product = getattr(settings, 'KEEL_PRODUCT_NAME', '').lower()
    if product:
        from keel.accounts.models import PRODUCT_ROLES
        roles = PRODUCT_ROLES.get(product, [])
        if roles:
            return [slug for slug, _label in roles]

    return ['admin']


def get_role_display(role):
    """Return display info for a role, with sensible defaults."""
    default = {
        'label': role.replace('_', ' ').title(),
        'icon': 'bi-person',
        'color': 'secondary',
    }
    return ROLE_DISPLAY.get(role, default)


@csrf_exempt
@require_POST
@rate_limit(max_requests=10, window=60)
def demo_login_view(request):
    """One-click demo login. POST with role= to log in as that demo user.

    GET requests intentionally return 405 (via ``@require_POST``); the URL
    is a form target, not a navigable page. Reach demo login by clicking
    a demo button on ``/accounts/login/`` (or ``/auth/login/``).

    Works with both legacy per-product User models and centralized
    KeelUser + ProductAccess. The demo user's username matches the role
    name, and ProductAccessMiddleware resolves the role from ProductAccess.

    CSRF-exempt because: (1) the DEMO_MODE gate below immediately returns
    403 on non-demo instances, (2) the role allowlist blocks arbitrary
    usernames, (3) the view is rate-limited 10/min. Exempting prevents
    403s from stale CSRF tokens on cached login pages — a common issue
    for reviewers clicking demo-login buttons from a browser tab that's
    been sitting open.
    """
    if not getattr(settings, 'DEMO_MODE', False):
        return _error(request, 'Demo mode is not enabled', 403)

    role = request.POST.get('role', '').strip()
    if not role:
        return _error(request, 'No role specified', 400)

    allowed_roles = get_demo_roles()
    if role not in allowed_roles:
        return _error(request, f'Invalid demo role: {role}', 400)

    user = authenticate(request, username=role, password=DEMO_PASSWORD)
    if user is not None:
        login(request, user)
        redirect_url = getattr(settings, 'LOGIN_REDIRECT_URL', '/dashboard/')
        return redirect(redirect_url)

    return _error(
        request,
        f'Demo user "{role}" is not seeded on this instance yet. '
        'Please try a different role or contact support.',
        500,
    )
