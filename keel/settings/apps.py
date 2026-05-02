"""Django app config for keel.settings."""
from django.apps import AppConfig


class KeelSettingsConfig(AppConfig):
    name = 'keel.settings'
    label = 'keel_settings'
    verbose_name = 'Keel Settings'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Register the built-in Notifications panel. Every product that
        # ships keel.notifications gets this panel for free without
        # writing per-product code.
        from .registry import register_panel
        from .builtin_panels import NotificationsPanel
        register_panel(NotificationsPanel())
