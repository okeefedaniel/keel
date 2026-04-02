"""Django app config for keel.search."""
from django.apps import AppConfig


class KeelSearchConfig(AppConfig):
    name = 'keel.search'
    label = 'keel_search'
    verbose_name = 'Keel Search'
    default_auto_field = 'django.db.models.BigAutoField'
