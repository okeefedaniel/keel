"""Shared context processors for DockLabs products.

Usage in settings.py:
    TEMPLATES = [{
        'OPTIONS': {
            'context_processors': [
                ...
                'keel.core.context_processors.site_context',
            ],
        },
    }]

    # Required setting:
    KEEL_PRODUCT_NAME = 'Beacon'  # or 'Harbor', 'Lookout', etc.
"""
from django.conf import settings
from django.utils import timezone


def site_context(request):
    """Inject site-wide template variables into every template context.

    Provides:
        SITE_NAME — from KEEL_PRODUCT_NAME setting
        CURRENT_YEAR — for copyright footers
        DEMO_MODE — whether demo login is enabled
        unread_notification_count — for authenticated users (notification bell)
    """
    context = {
        'SITE_NAME': getattr(settings, 'KEEL_PRODUCT_NAME', 'DockLabs'),
        'CURRENT_YEAR': timezone.now().year,
        'DEMO_MODE': getattr(settings, 'DEMO_MODE', False),
    }

    if hasattr(request, 'user') and request.user.is_authenticated:
        # Try to resolve the notification count via the configured model
        # first (most reliable), then fall back to related manager names.
        model_path = getattr(settings, 'KEEL_NOTIFICATION_MODEL', None)
        if model_path:
            try:
                from django.apps import apps
                NotifModel = apps.get_model(model_path)
                context['unread_notification_count'] = (
                    NotifModel.objects.filter(
                        recipient=request.user, is_read=False,
                    ).count()
                )
            except (LookupError, Exception):
                pass
        else:
            # Fallback: try common related manager names from
            # AbstractNotification's %(app_label)s_notifications pattern.
            for attr in ('notifications', 'core_notifications'):
                manager = getattr(request.user, attr, None)
                if manager is not None:
                    context['unread_notification_count'] = (
                        manager.filter(is_read=False).count()
                    )
                    break

    return context
