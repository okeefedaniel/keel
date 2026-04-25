from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'keel.scheduling'
    label = 'keel_scheduling'
    verbose_name = 'Keel Scheduling'
