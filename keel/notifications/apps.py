"""Django app config for keel.notifications."""
from django.apps import AppConfig


class KeelNotificationsConfig(AppConfig):
    name = 'keel.notifications'
    label = 'keel_notifications'
    verbose_name = 'Keel Notifications'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Register all product notification types for the admin matrix.
        # Products also register their own types at runtime for dispatch,
        # but this gives Keel visibility into the full catalog.
        from .product_types import register_all_product_types
        from .registry import apply_overrides
        register_all_product_types()
        # Load admin overrides from the database on top of hardcoded defaults.
        apply_overrides()
