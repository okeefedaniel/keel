from django.apps import AppConfig


class OpsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'keel.ops'
    label = 'keel_ops'
    verbose_name = 'Keel Ops'
