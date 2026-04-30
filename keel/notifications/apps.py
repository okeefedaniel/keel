"""Django app config for keel.notifications."""
from django.apps import AppConfig


class KeelNotificationsConfig(AppConfig):
    name = 'keel.notifications'
    label = 'keel_notifications'
    verbose_name = 'Keel Notifications'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from django.conf import settings
        from .product_types import (
            register_all_product_types,
            register_keel_platform_types,
        )
        from .registry import apply_overrides

        # Cross-cutting platform types (change requests, security alerts)
        # belong on every deployment.
        register_keel_platform_types()

        # Only the Keel admin console needs the full suite-wide catalog so
        # its notification-type matrix can show routing across all products.
        # On product deployments, each product's own AppConfig.ready()
        # registers its runtime types; importing other products' types here
        # would pollute the preferences UI with categories the user can't act on.
        if getattr(settings, 'KEEL_PRODUCT_NAME', '') == 'Keel':
            register_all_product_types()

        # Load admin overrides from the database on top of hardcoded defaults.
        apply_overrides()
