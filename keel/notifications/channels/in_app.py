"""In-app notification channel — creates a database record."""
import logging

from django.apps import apps
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_notification_model():
    """Resolve the Notification model from settings."""
    model_path = getattr(settings, 'KEEL_NOTIFICATION_MODEL', None)
    if model_path:
        return apps.get_model(model_path)
    audit_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    app_label = audit_path.split('.')[0]
    return apps.get_model(f'{app_label}.Notification')


def send_in_app(recipient, title, message, link='', priority='medium',
                notification_type='', **kwargs):
    """Create an in-app notification record.

    Args:
        recipient: User instance.
        title: Short notification title.
        message: Full notification message.
        link: URL to link to (relative path).
        priority: 'low', 'medium', 'high', 'urgent'.
        notification_type: Registry key for tracking.

    Returns:
        (success: bool, error_message: str)
    """
    try:
        Notification = _get_notification_model()
        Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            link=link,
            priority=priority,
        )
        return True, ''
    except Exception as e:
        logger.exception('Failed to create in-app notification for %s', recipient)
        return False, str(e)
