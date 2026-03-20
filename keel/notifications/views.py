"""Shared notification views for all DockLabs products.

Usage in urls.py:
    path('notifications/', include('keel.notifications.urls')),

This provides:
    /notifications/                 — list all notifications
    /notifications/<pk>/read/       — mark one as read (POST)
    /notifications/mark-all-read/   — mark all as read (POST)
    /notifications/preferences/     — manage notification preferences
"""
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .registry import get_all_types, get_types_by_category

logger = logging.getLogger(__name__)


def _get_notification_model():
    model_path = getattr(settings, 'KEEL_NOTIFICATION_MODEL', None)
    if model_path:
        return apps.get_model(model_path)
    audit_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    app_label = audit_path.split('.')[0]
    return apps.get_model(f'{app_label}.Notification')


def _get_preference_model():
    model_path = getattr(settings, 'KEEL_NOTIFICATION_PREFERENCE_MODEL', None)
    if model_path:
        return apps.get_model(model_path)
    return None


# ---------------------------------------------------------------------------
# Notification List
# ---------------------------------------------------------------------------

@login_required
def notification_list(request):
    """List all notifications for the current user."""
    Notification = _get_notification_model()
    notifications = Notification.objects.filter(
        recipient=request.user,
    ).order_by('-created_at')

    # Filter by read/unread
    filter_status = request.GET.get('status', '')
    if filter_status == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_status == 'read':
        notifications = notifications.filter(is_read=True)

    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(notifications, 25)
    page = request.GET.get('page')
    notifications_page = paginator.get_page(page)

    unread_count = Notification.objects.filter(
        recipient=request.user, is_read=False,
    ).count()

    context = {
        'notifications': notifications_page,
        'unread_count': unread_count,
        'filter_status': filter_status,
    }
    return render(request, 'notifications/list.html', context)


# ---------------------------------------------------------------------------
# Mark as Read
# ---------------------------------------------------------------------------

@login_required
@require_POST
def mark_read(request, pk):
    """Mark a single notification as read."""
    Notification = _get_notification_model()
    notification = get_object_or_404(
        Notification, pk=pk, recipient=request.user,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=['is_read', 'read_at'])

    if request.headers.get('HX-Request'):
        return JsonResponse({'status': 'ok'})
    return redirect('keel_notifications:list')


@login_required
@require_POST
def mark_all_read(request):
    """Mark all unread notifications as read for the current user."""
    Notification = _get_notification_model()
    updated = Notification.objects.filter(
        recipient=request.user, is_read=False,
    ).update(is_read=True, read_at=timezone.now())

    if request.headers.get('HX-Request'):
        return JsonResponse({'status': 'ok', 'count': updated})
    return redirect('keel_notifications:list')


# ---------------------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------------------

@login_required
def preferences(request):
    """View and update notification preferences."""
    PrefModel = _get_preference_model()
    if PrefModel is None:
        # Preferences not configured for this product
        return render(request, 'notifications/preferences.html', {
            'categories': {},
            'preferences': {},
            'prefs_enabled': False,
        })

    types_by_category = get_types_by_category()

    if request.method == 'POST':
        _save_preferences(request, PrefModel, types_by_category)
        return redirect('keel_notifications:preferences')

    # Load current preferences
    user_prefs = {
        p.notification_type: p
        for p in PrefModel.objects.filter(user=request.user)
    }

    context = {
        'categories': types_by_category,
        'preferences': user_prefs,
        'prefs_enabled': True,
        'sms_available': bool(getattr(settings, 'KEEL_SMS_BACKEND', None)),
        'user_has_phone': bool(getattr(request.user, 'phone', None)),
    }
    return render(request, 'notifications/preferences.html', context)


def _save_preferences(request, PrefModel, types_by_category):
    """Process the preferences form POST."""
    all_types = get_all_types()

    for key, ntype in all_types.items():
        if not ntype.allow_mute:
            continue

        pref, created = PrefModel.objects.get_or_create(
            user=request.user,
            notification_type=key,
            defaults={
                'channel_in_app': True,
                'channel_email': 'email' in ntype.default_channels,
                'channel_sms': False,
            },
        )

        pref.is_muted = request.POST.get(f'{key}_muted') == 'on'
        pref.channel_in_app = request.POST.get(f'{key}_in_app') == 'on'
        pref.channel_email = request.POST.get(f'{key}_email') == 'on'
        pref.channel_sms = request.POST.get(f'{key}_sms') == 'on'
        pref.save()
