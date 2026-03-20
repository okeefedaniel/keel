"""Django app config for keel.notifications."""
from django.apps import AppConfig


class KeelNotificationsConfig(AppConfig):
    name = 'keel.notifications'
    label = 'keel_notifications'
    verbose_name = 'Keel Notifications'
    default_auto_field = 'django.db.models.BigAutoField'
