"""
Automatic audit logging via Django signals — shared across DockLabs products.

Products register models for auto-audit in their AppConfig.ready():

    from keel.core.audit_signals import register_audited_model

    register_audited_model('companies.Company', 'Company')
    register_audited_model('interactions.Task', 'Task',
                           skip_fields={'custom_noisy_field'})

Keel's AuditMiddleware must be active (sets request.audit_ip), and
products must include it in MIDDLEWARE. The middleware also populates
thread-local context so signals know which user performed the action.

All registered models get post_save and post_delete signals that
auto-create AuditLog entries via log_audit().
"""
import logging
import threading
from dataclasses import dataclass, field

from django.db.models.signals import post_save, post_delete

logger = logging.getLogger(__name__)

# ── Thread-local storage for current request context ────────────────

_thread_locals = threading.local()


def set_audit_context(user=None, ip_address=None):
    """Called by middleware on each request to store the actor."""
    _thread_locals.audit_user = user
    _thread_locals.audit_ip = ip_address


def get_audit_context():
    """Retrieve the current request's user and IP."""
    user = getattr(_thread_locals, 'audit_user', None)
    ip = getattr(_thread_locals, 'audit_ip', None)
    return user, ip


# ── Registry ────────────────────────────────────────────────────────

@dataclass
class AuditedModel:
    """Definition of a model to auto-audit via signals."""
    model_label: str
    display_name: str
    skip_fields: set = field(default_factory=set)


_registry: dict[str, AuditedModel] = {}

# Fields to always skip (noisy, auto-set, or sensitive)
_DEFAULT_SKIP_FIELDS = {
    'updated_at', 'created_at', 'search_vector', 'password', 'last_login',
}


def register_audited_model(model_label, display_name, skip_fields=None):
    """Register a model for automatic audit logging.

    Args:
        model_label: 'app.Model' format (e.g. 'companies.Company').
        display_name: Human-readable name for audit log entries.
        skip_fields: Optional set of field names to exclude from changes.
            Merged with default skip fields (updated_at, password, etc.).
    """
    merged_skip = _DEFAULT_SKIP_FIELDS | (skip_fields or set())
    _registry[model_label] = AuditedModel(
        model_label=model_label,
        display_name=display_name,
        skip_fields=merged_skip,
    )


def get_audited_models():
    """Return all registered audited models."""
    return dict(_registry)


# ── Signal handlers ─────────────────────────────────────────────────

def _describe(instance):
    return str(instance)[:200]


def _compute_changes(instance, skip_fields):
    """Compute a field-value dict for the audit log."""
    changes = {}
    for f in instance._meta.concrete_fields:
        if f.name in skip_fields:
            continue
        if f.is_relation:
            val = getattr(instance, f'{f.name}_id', None)
            if val is not None:
                changes[f.name] = str(val)
        else:
            val = getattr(instance, f.name, None)
            if val is not None and val != '' and val != [] and val != {}:
                changes[f.name] = str(val)[:500]
    return changes


def _on_save(sender, instance, created, **kwargs):
    model_label = f'{sender._meta.app_label}.{sender.__name__}'
    entry = _registry.get(model_label)
    if not entry:
        return

    user, ip = get_audit_context()
    action = 'create' if created else 'update'
    changes = _compute_changes(instance, entry.skip_fields)

    try:
        from keel.core.audit import log_audit
        log_audit(
            user=user,
            action=action,
            entity_type=entry.display_name,
            entity_id=str(instance.pk),
            description=f'{"Created" if created else "Updated"} {entry.display_name}: {_describe(instance)}',
            changes=changes,
            ip_address=ip,
        )
    except Exception:
        logger.exception('Auto-audit failed for %s %s', action, model_label)


def _on_delete(sender, instance, **kwargs):
    model_label = f'{sender._meta.app_label}.{sender.__name__}'
    entry = _registry.get(model_label)
    if not entry:
        return

    user, ip = get_audit_context()

    try:
        from keel.core.audit import log_audit
        log_audit(
            user=user,
            action='delete',
            entity_type=entry.display_name,
            entity_id=str(instance.pk),
            description=f'Deleted {entry.display_name}: {_describe(instance)}',
            changes={},
            ip_address=ip,
        )
    except Exception:
        logger.exception('Auto-audit failed for delete %s', model_label)


# ── Signal connection ───────────────────────────────────────────────

def connect_audit_signals():
    """Connect post_save and post_delete signals for all registered models.

    Called from KeelCoreConfig.ready() — runs after all product
    AppConfigs have registered their audited models.
    """
    from django.apps import apps

    connected = 0
    for model_label in _registry:
        try:
            model = apps.get_model(model_label)
            post_save.connect(_on_save, sender=model,
                              dispatch_uid=f'keel_audit_save_{model_label}')
            post_delete.connect(_on_delete, sender=model,
                                dispatch_uid=f'keel_audit_delete_{model_label}')
            connected += 1
        except LookupError:
            # Model not installed (e.g., FOIA models on a non-FOIA instance)
            logger.debug('Audit model %s not found, skipping', model_label)

    if connected:
        logger.debug('Audit signals connected for %d models', connected)
