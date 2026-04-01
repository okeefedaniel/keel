from django.apps import AppConfig


class CalendarConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'keel.calendar'
    label = 'keel_calendar'
    verbose_name = 'Keel Calendar'
