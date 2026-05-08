"""Django app config for keel.ai."""
from django.apps import AppConfig


class KeelAIConfig(AppConfig):
    name = 'keel.ai'
    label = 'keel_ai'
    verbose_name = 'Keel AI'
    default_auto_field = 'django.db.models.BigAutoField'
