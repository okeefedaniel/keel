"""Keel audit middleware — shared across all DockLabs products.

Usage in settings.py:
    MIDDLEWARE = [
        ...
        'keel.core.middleware.AuditMiddleware',
    ]

    # Tell Keel which AuditLog model to use
    KEEL_AUDIT_LOG_MODEL = 'core.AuditLog'
"""
import logging

from django.apps import apps
from django.contrib.auth.signals import user_logged_in

logger = logging.getLogger(__name__)


def _get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _get_audit_log_model():
    """Resolve the AuditLog model from settings."""
    from django.conf import settings
    model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    return apps.get_model(model_path)


def _handle_user_logged_in(sender, request, user, **kwargs):
    ip_address = getattr(request, 'audit_ip', None) if request else None
    try:
        AuditLog = _get_audit_log_model()
        AuditLog.objects.create(
            user=user,
            action='login',
            entity_type='User',
            entity_id=str(user.pk),
            description=f'User {user} logged in.',
            changes={},
            ip_address=ip_address,
        )
    except Exception:
        logger.exception('Failed to create login audit log entry')


class AuditMiddleware:
    """Captures per-request audit metadata and logs login events."""

    def __init__(self, get_response):
        self.get_response = get_response
        user_logged_in.connect(_handle_user_logged_in)

    def __call__(self, request):
        request.audit_ip = _get_client_ip(request)
        response = self.get_response(request)
        return response
