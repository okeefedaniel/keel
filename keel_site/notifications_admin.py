"""Notification flow diagram and routing admin.

Shows a visual map of who gets notified of what across all products,
and allows adjusting the routing logic from the admin console.
"""
import json

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from keel.accounts.models import ProductAccess, get_product_roles
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
        })

    # Group by category for display
    categories = {}
    for item in flow_data:
        cat = item['category']
        categories.setdefault(cat, []).append(item)

    # Channel summary stats
    channel_stats = {'in_app': 0, 'email': 0, 'sms': 0}
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

    context = {
        'categories': categories,
        'channel_stats': channel_stats,
        'role_coverage': role_coverage,
        'total_types': len(all_types),
        'product_roles': product_roles,
        'flow_data_json': json.dumps(flow_data),
        'sms_configured': sms_configured,
        'email_backend': email_backend,
    }
    return render(request, 'notifications/flow.html', context)


@admin_required
@require_POST
def update_notification_type(request):
    """Update the routing for a notification type (channels, roles, priority)."""
    key = request.POST.get('key', '')
    ntype = _registry.get(key)
    if not ntype:
        return JsonResponse({'error': f'Unknown type: {key}'}, status=404)

    # Update channels
    channels = request.POST.getlist('channels')
    if channels:
        ntype.default_channels = channels

    # Update roles
    roles = request.POST.getlist('roles')
    if roles:
        ntype.default_roles = roles

    # Update priority
    priority = request.POST.get('priority', '')
    if priority in ('low', 'medium', 'high', 'urgent'):
        ntype.priority = priority

    # Update mutability
    allow_mute = request.POST.get('allow_mute')
    if allow_mute is not None:
        ntype.allow_mute = allow_mute == 'true'

    return JsonResponse({
        'status': 'ok',
        'key': key,
        'channels': ntype.default_channels,
        'roles': ntype.default_roles,
        'priority': ntype.priority,
    })
