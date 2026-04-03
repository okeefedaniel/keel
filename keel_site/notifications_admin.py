"""Notification flow diagram and routing admin.

Shows a visual map of who gets notified of what across all products,
and allows adjusting the routing logic from the admin console.
"""
import hmac
import json

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from keel.accounts.models import NotificationTypeOverride, ProductAccess, get_product_roles
from keel.notifications.registry import (
    NotificationType,
    get_all_types,
    get_types_by_category,
    register,
    _registry,
)


def _admin_check(user):
    if user.is_superuser:
        return True
    return ProductAccess.objects.filter(
        user=user, role__in=('admin', 'system_admin'), is_active=True,
    ).exists()


def admin_required(view_func):
    from functools import wraps

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not _admin_check(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


@admin_required
def notification_flow(request):
    """Visual map of notification routing across all products."""
    types_by_category = get_types_by_category()
    all_types = get_all_types()
    product_roles = get_product_roles()

    # Load database overrides to highlight customized types
    override_keys = set()
    override_count = 0
    try:
        overrides = NotificationTypeOverride.objects.values_list('key', flat=True)
        override_keys = set(overrides)
        override_count = len(override_keys)
    except Exception:
        pass

    # Build structured data for the diagram
    flow_data = []
    for key, ntype in sorted(all_types.items(), key=lambda x: (x[1].category, x[0])):
        flow_data.append({
            'key': key,
            'label': ntype.label,
            'description': ntype.description,
            'category': ntype.category,
            'channels': ntype.default_channels,
            'roles': ntype.default_roles,
            'priority': ntype.priority,
            'allow_mute': ntype.allow_mute,
            'has_email_template': bool(ntype.email_template),
            'has_custom_resolver': bool(ntype.recipient_resolver),
            'agency_scoped': ntype.agency_scoped,
            'has_link_template': bool(ntype.link_template),
            'has_override': key in override_keys,
        })

    # Group by category for display
    categories = {}
    for item in flow_data:
        cat = item['category']
        categories.setdefault(cat, []).append(item)

    # Channel summary stats (include boswell)
    channel_stats = {'in_app': 0, 'email': 0, 'sms': 0, 'boswell': 0}
    for ntype in all_types.values():
        for ch in ntype.default_channels:
            channel_stats[ch] = channel_stats.get(ch, 0) + 1

    # Role coverage — which roles receive notifications
    role_coverage = {}
    for ntype in all_types.values():
        for role in ntype.default_roles:
            role_coverage.setdefault(role, []).append(ntype.key)

    # Channel config status
    sms_configured = bool(getattr(django_settings, 'KEEL_SMS_BACKEND', None))
    email_backend = getattr(django_settings, 'EMAIL_BACKEND', '').split('.')[-1]

    # Build the routing matrix: rows = notification types, cols = roles
    all_roles = sorted(role_coverage.keys())
    matrix_rows = []
    for item in flow_data:
        cells = []
        for role in all_roles:
            if role in item['roles'] or 'all' in item['roles']:
                cells.append(item['channels'])
            else:
                cells.append([])
        matrix_rows.append({
            'key': item['key'],
            'label': item['label'],
            'category': item['category'],
            'priority': item['priority'],
            'has_override': item['has_override'],
            'cells': cells,  # parallel with matrix_roles
        })

    # Orphaned overrides: DB overrides for types no longer in registry
    orphaned_overrides = override_keys - set(all_types.keys())

    context = {
        'categories': categories,
        'channel_stats': channel_stats,
        'role_coverage': role_coverage,
        'total_types': len(all_types),
        'product_roles': product_roles,
        'flow_data_json': json.dumps(flow_data),
        'sms_configured': sms_configured,
        'email_backend': email_backend,
        'matrix_rows': matrix_rows,
        'matrix_roles': all_roles,
        'override_count': override_count,
        'override_keys': override_keys,
        'orphaned_overrides': orphaned_overrides,
    }
    return render(request, 'notifications/flow.html', context)


@admin_required
@require_POST
def update_notification_type(request):
    """Update the routing for a notification type (channels, roles, priority).

    Mutates the in-memory registry AND persists to the database so changes
    survive server restarts and can be synced to product deployments.
    """
    key = request.POST.get('key', '')
    ntype = _registry.get(key)
    if not ntype:
        return JsonResponse({'error': f'Unknown type: {key}'}, status=404)

    # Update in-memory registry
    channels = request.POST.getlist('channels')
    if channels:
        ntype.default_channels = channels

    roles = request.POST.getlist('roles')
    if roles:
        ntype.default_roles = roles

    priority = request.POST.get('priority', '')
    if priority in ('low', 'medium', 'high', 'urgent'):
        ntype.priority = priority

    allow_mute = request.POST.get('allow_mute')
    if allow_mute is not None:
        ntype.allow_mute = allow_mute == 'true'

    # Persist to database
    NotificationTypeOverride.objects.update_or_create(
        key=key,
        defaults={
            'channels': ntype.default_channels,
            'roles': ntype.default_roles,
            'priority': ntype.priority,
            'allow_mute': ntype.allow_mute,
            'updated_by': request.user,
        },
    )

    return JsonResponse({
        'status': 'ok',
        'key': key,
        'channels': ntype.default_channels,
        'roles': ntype.default_roles,
        'priority': ntype.priority,
    })


# =========================================================================
# Product sync API — products fetch merged notification config from Keel
# =========================================================================
@csrf_exempt
def api_notification_config(request):
    """Return the merged notification config for products to sync.

    Products call GET /api/notifications/config/ with
    Authorization: Bearer <KEEL_API_KEY>

    Optional query param: ?product=harbor to filter by category prefix.
    """
    if request.method == 'OPTIONS':
        response = JsonResponse({})
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        return response

    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    # Verify API key
    api_key = getattr(django_settings, 'KEEL_API_KEY', '') or ''
    if not api_key:
        return JsonResponse({'error': 'API not configured.'}, status=503)

    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer ') or not hmac.compare_digest(
        auth_header[7:].strip(), api_key
    ):
        return JsonResponse({'error': 'Invalid API key.'}, status=401)

    product_filter = request.GET.get('product', '').lower()
    all_types = get_all_types()

    config = []
    for key, ntype in sorted(all_types.items()):
        if product_filter and not ntype.category.lower().startswith(product_filter):
            continue
        config.append({
            'key': key,
            'label': ntype.label,
            'description': ntype.description,
            'category': ntype.category,
            'default_channels': ntype.default_channels,
            'default_roles': ntype.default_roles,
            'priority': ntype.priority,
            'allow_mute': ntype.allow_mute,
            'agency_scoped': ntype.agency_scoped,
            'agency_field': ntype.agency_field,
        })

    return JsonResponse({'types': config, 'count': len(config)})
