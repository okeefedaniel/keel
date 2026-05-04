"""Django app config for keel.settings."""
from django.apps import AppConfig


class KeelSettingsConfig(AppConfig):
    name = 'keel.settings'
    label = 'keel_settings'
    verbose_name = 'Keel Settings'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Register the built-in panels. Every product that ships keel
        # gets these for free without writing per-product code. Visibility
        # of each panel is gated by deployment mode at render time —
        # see ``builtin_panels.py`` docstrings for the rules.
        from .registry import register_panel
        from .builtin_panels import (
            AccountPanel, NotificationsPanel, ProfilePanel,
        )
        register_panel(ProfilePanel())
        register_panel(AccountPanel())
        register_panel(NotificationsPanel())
