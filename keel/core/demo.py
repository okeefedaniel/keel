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
    Password = 'demo2026!' (all accounts)
"""
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .utils import rate_limit

DEMO_PASSWORD = 'demo2026!'

# Display labels and icons for common roles across DockLabs products
ROLE_DISPLAY = {
    # Lookout
    'admin': {'label': 'Admin', 'icon': 'bi-shield-check', 'color': 'danger'},
    'legislative_aid': {'label': 'Legislative Aid', 'icon': 'bi-person-badge', 'color': 'primary'},
    'stakeholder': {'label': 'Stakeholder', 'icon': 'bi-people', 'color': 'info'},
    # Beacon
    'relationship_manager': {'label': 'Relationship Manager', 'icon': 'bi-person-lines-fill', 'color': 'primary'},
    'foia_attorney': {'label': 'FOIA Attorney', 'icon': 'bi-briefcase', 'color': 'warning'},
    'quasi_rm': {'label': 'Quasi RM', 'icon': 'bi-building', 'color': 'secondary'},
    # Harbor
    'grants_manager': {'label': 'Grants Manager', 'icon': 'bi-cash-stack', 'color': 'success'},
    'reviewer': {'label': 'Reviewer', 'icon': 'bi-clipboard-check', 'color': 'info'},
}


def get_demo_roles():
    """Return the list of demo roles configured for this product."""
    return getattr(settings, 'DEMO_ROLES', ['admin'])


def get_role_display(role):
    """Return display info for a role, with sensible defaults."""
    default = {
        'label': role.replace('_', ' ').title(),
        'icon': 'bi-person',
        'color': 'secondary',
    }
    return ROLE_DISPLAY.get(role, default)


@require_POST
@rate_limit(max_requests=10, window=60)
def demo_login_view(request):
    """One-click demo login. POST with role= to log in as that demo user."""
    if not getattr(settings, 'DEMO_MODE', False):
        return JsonResponse({'error': 'Demo mode is not enabled'}, status=403)

    role = request.POST.get('role', '').strip()
    if not role:
        return JsonResponse({'error': 'No role specified'}, status=400)

    allowed_roles = get_demo_roles()
    if role not in allowed_roles:
        return JsonResponse({'error': f'Invalid demo role: {role}'}, status=400)

    user = authenticate(request, username=role, password=DEMO_PASSWORD)
    if user is not None:
        login(request, user)
        redirect_url = getattr(settings, 'LOGIN_REDIRECT_URL', '/dashboard/')
        return redirect(redirect_url)

    return JsonResponse(
        {'error': f'Demo user "{role}" not found. Run seed_demo_users.'},
        status=500,
    )
