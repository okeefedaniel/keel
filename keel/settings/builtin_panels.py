"""Built-in settings panels shipped with keel itself.

Today: just the Notifications panel, which reuses the existing
`keel.notifications.views.preferences` rendering. Future: account/auth
panels (e.g. password change, MFA, sessions) can land here.

The standalone `/notifications/preferences/` URL stays live for
backwards compat (existing direct links, redirect targets, etc.); it
renders the same form. Eventually we can deprecate it in favor of
`/settings/notifications/`.
"""
import logging
import os

from django.conf import settings as django_settings

from .base import SettingsPanel

logger = logging.getLogger(__name__)


class NotificationsPanel(SettingsPanel):
    """Per-user notification channel preferences.

    Rendered visible whenever `keel.notifications` is installed AND the
    deployment has a `KEEL_NOTIFICATION_PREFERENCE_MODEL` configured.
    Standalone deployments without notifications still see the empty
    settings page rather than a broken panel.
    """

    slug = 'notifications'
    label = 'Notifications'
    icon = 'bi-bell'
    order = 50  # Mid-priority; product-specific Profile/Account panels float above
    description = 'Channels you receive each notification type on'

    def is_visible(self, user) -> bool:
        if not super().is_visible(user):
            return False
        # Only show when the prefs model is configured.
        from keel.notifications.views import _get_preference_model
        return _get_preference_model() is not None

    def get_context(self, request) -> dict:
        from keel.notifications.registry import get_types_by_category
        from keel.notifications.views import _boswell_available, _get_preference_model

        PrefModel = _get_preference_model()
        product_prefixes = getattr(django_settings, 'KEEL_NOTIFICATION_CATEGORIES', None)
        types_by_category = get_types_by_category()
        if product_prefixes:
            types_by_category = {
                cat: types for cat, types in types_by_category.items()
                if any(cat.startswith(p) for p in product_prefixes)
            }

        try:
            user_prefs = {
                p.notification_type: p
                for p in PrefModel.objects.filter(user=request.user)
            }
        except Exception:
            logger.exception('settings.notifications: failed to load prefs')
            user_prefs = {}

        return {
            'categories': types_by_category,
            'preferences': user_prefs,
            'prefs_enabled': True,
            'sms_available': bool(
                getattr(django_settings, 'KEEL_SMS_BACKEND', None)
                or os.environ.get('KEEL_SMS_BACKEND')
            ),
            'user_has_phone': bool(getattr(request.user, 'phone', None)),
            'boswell_available': _boswell_available(types_by_category),
        }

    def post(self, request):
        from keel.notifications.registry import get_types_by_category
        from keel.notifications.views import _get_preference_model, _save_preferences

        PrefModel = _get_preference_model()
        if PrefModel is None:
            return None  # No-op success — nothing to save.

        product_prefixes = getattr(django_settings, 'KEEL_NOTIFICATION_CATEGORIES', None)
        types_by_category = get_types_by_category()
        if product_prefixes:
            types_by_category = {
                cat: types for cat, types in types_by_category.items()
                if any(cat.startswith(p) for p in product_prefixes)
            }
        _save_preferences(request, PrefModel, types_by_category)
        return None  # framework adds success message + redirects
