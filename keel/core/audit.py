"""Audit logging helper shared across DockLabs products.

Usage:
    from keel.core.audit import log_audit

    log_audit(
        user=request.user,
        action='create',
        entity_type='Application',
        entity_id=str(app.pk),
        description='Created new application',
        changes={'status': ['', 'draft']},
        ip_address=request.audit_ip,
    )

Requires KEEL_AUDIT_LOG_MODEL in settings (e.g., 'core.AuditLog').
"""
import logging

from django.apps import apps
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_audit_log_model():
    """Resolve the AuditLog model from KEEL_AUDIT_LOG_MODEL setting."""
    model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    return apps.get_model(model_path)


def log_audit(user, action, entity_type, entity_id, description='',
              changes=None, ip_address=None):
    """Create an immutable AuditLog entry.

    Args:
        user: User instance or None (for system actions).
        action: One of the AuditLog.Action choices (e.g., 'create', 'update').
        entity_type: String like 'Application', 'Award', 'Company', etc.
        entity_id: String ID of the entity.
        description: Human-readable description of the action.
        changes: Dict of changes (e.g., {'status': ['draft', 'submitted']}).
        ip_address: Client IP address (available via request.audit_ip
            when AuditMiddleware is active).
    """
    try:
        AuditLog = _get_audit_log_model()
        AuditLog.objects.create(
            user=user,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            description=description,
            changes=changes or {},
            ip_address=ip_address,
        )
    except Exception:
        logger.exception('Failed to create audit log entry')
