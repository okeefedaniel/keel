"""Django app config for keel.mentions."""
from __future__ import annotations

from django.apps import AppConfig


class KeelMentionsConfig(AppConfig):
    name = 'keel.mentions'
    label = 'keel_mentions'
    verbose_name = 'Keel Mentions'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Register the notification type so the preferences UI can pick it up.
        from .notification_types import register_mention_types
        register_mention_types()

        # Wire the Django system checks (W001/W002/W003) so misconfiguration
        # is loud at boot, not silent at first user mention.
        from . import checks  # noqa: F401 — import side-effect registers checks
