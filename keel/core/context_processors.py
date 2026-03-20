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
        # Use the related_name from AbstractNotification; products should
        # ensure their Notification model's related_name resolves here.
        # The %(app_label)s_notifications pattern means we need to try
        # the most common related manager names.
        for attr in ('notifications', 'core_notifications'):
            manager = getattr(request.user, attr, None)
            if manager is not None:
                context['unread_notification_count'] = (
                    manager.filter(is_read=False).count()
                )
                break

    return context
