"""Django app config for keel.signatures."""
from django.apps import AppConfig


class KeelSignaturesConfig(AppConfig):
    name = 'keel.signatures'
    label = 'keel_signatures'
    verbose_name = 'Keel Signatures'
    default_auto_field = 'django.db.models.BigAutoField'
