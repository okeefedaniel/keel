from django.apps import AppConfig


class CommsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'keel.comms'
    label = 'keel_comms'
    verbose_name = 'Keel Communications'
