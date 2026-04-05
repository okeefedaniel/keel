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
from django.urls import NoReverseMatch, reverse
from django.utils import timezone


def _safe_reverse(url_name):
    """Return the URL for *url_name*, or ``None`` if it is not registered."""
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return None


def _microsoft_login_url(request):
    """Resolve the Microsoft SSO login URL.

    Tries the convenience ``microsoft_login`` named URL first (defined by
    most products), then falls back to the allauth provider API.
    """
    url = _safe_reverse('microsoft_login')
    if url:
        return url

    # Fallback: ask allauth's provider registry for the URL.
    try:
        from allauth.socialaccount.providers import registry
        provider = registry.by_id('microsoft', request)
        return provider.get_login_url(request, process='login')
    except Exception:
        return None


def site_context(request):
    """Inject site-wide template variables into every template context.

    Provides:
        SITE_NAME — from KEEL_PRODUCT_NAME setting
        CURRENT_YEAR — for copyright footers
        DEMO_MODE — whether demo login is enabled
        unread_notification_count — for authenticated users (notification bell)

    Auth URLs (for the shared login card):
        register_url — allauth signup page
        reset_password_url — allauth password-reset page
        microsoft_login_url — Microsoft Entra ID SSO entry-point
    """
    context = {
        'SITE_NAME': getattr(settings, 'KEEL_PRODUCT_NAME', 'DockLabs'),
        'PRODUCT_ICON': getattr(settings, 'KEEL_PRODUCT_ICON', 'bi-gear'),
        'PRODUCT_SUBTITLE': getattr(settings, 'KEEL_PRODUCT_SUBTITLE', ''),
        'CURRENT_YEAR': timezone.now().year,
        'DEMO_MODE': getattr(settings, 'DEMO_MODE', False),
    }

    # ── Auth URLs for the shared login card ──────────────────────────
    register_url = _safe_reverse('account_signup')
    if register_url:
        context['register_url'] = register_url

    reset_password_url = (
        _safe_reverse('account_reset_password')
        or _safe_reverse('password_reset')
    )
    if reset_password_url:
        context['reset_password_url'] = reset_password_url

    ms_url = _microsoft_login_url(request)
    if ms_url:
        context['microsoft_login_url'] = ms_url

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
