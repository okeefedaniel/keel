"""
Keel Notifications — event-driven notification system for DockLabs products.

Architecture: Event → Registry → Preferences → Channel Dispatchers

Usage in products:

    # 1. Register notification types (in apps.py ready() or notifications.py)
    from keel.notifications import register, NotificationType

    register(NotificationType(
        key='application_submitted',
        label='New Application Submitted',
        default_channels=['in_app', 'email'],
        default_roles=['system_admin', 'agency_admin', 'program_officer'],
        priority='medium',
        email_template='emails/application_submitted.html',
    ))

    # 2. Send notifications from views/services
    from keel.notifications import notify

    notify(
        event='application_submitted',
        actor=request.user,
        context={'application': app_obj},
        # Recipients auto-resolved from role registry + user preferences
    )

    # 3. Include URLs for notification list + preferences
    path('notifications/', include('keel.notifications.urls')),

Settings:
    KEEL_NOTIFICATION_MODEL = 'core.Notification'
    KEEL_NOTIFICATION_PREFERENCE_MODEL = 'core.NotificationPreference'  # optional
    KEEL_SMS_BACKEND = 'twilio'  # or None to disable
    TWILIO_ACCOUNT_SID = '...'
    TWILIO_AUTH_TOKEN = '...'
    TWILIO_FROM_NUMBER = '+1...'
"""
from .registry import NotificationType, register, get_type, get_all_types
from .dispatch import notify

__all__ = [
    'NotificationType',
    'register',
    'get_type',
    'get_all_types',
    'notify',
]
