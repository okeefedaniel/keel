"""Keel audit middleware — shared across all DockLabs products.

Usage in settings.py:
    MIDDLEWARE = [
        ...
        'keel.core.middleware.AuditMiddleware',
    ]

    # Tell Keel which AuditLog model to use
    KEEL_AUDIT_LOG_MODEL = 'core.AuditLog'

Outside a request context — Celery tasks, ``./manage.py shell`` mutations, data
migrations that need user attribution — use the ``audit_context`` context
manager (below) to set the thread-local user, so auto-audit signal handlers
attribute the resulting AuditLog rows correctly. Without the context manager,
the v0.46.3 gate causes non-request mutations to skip audit entirely; the
context manager is the escape hatch that re-enables audit for explicitly
user-attributable async / shell work.
"""
import logging
from contextlib import contextmanager

from django.apps import apps
from django.contrib.auth.signals import user_logged_in

logger = logging.getLogger(__name__)


@contextmanager
def audit_context(user, ip=''):
    """Re-establish thread-local audit context outside a request.

    The keel v0.46.3 audit gate makes any mutation with ``user=None`` in
    thread-local skip the audit row entirely. That is the right default for
    cron / management / migration contexts, but it's wrong for the narrow
    case of code that IS doing user-attributable work without a Django
    request — Celery tasks acting on behalf of a user, shell sessions
    performing operator interventions, data migrations applying a known
    operator change.

    Wrap that code in ``with audit_context(user=actor, ip=''): ...`` and the
    auto-audit signals re-engage for the duration of the block. Thread-local
    is restored to its prior state on exit, so nesting is safe.

    Examples::

        # Celery task on behalf of a user
        @shared_task
        def archive_project(project_id, user_id):
            user = KeelUser.objects.get(pk=user_id)
            with audit_context(user=user):
                project = Project.objects.get(pk=project_id)
                project.archive()  # signal fires with user attribution

        # Operator shell intervention
        >>> from keel.core.middleware import audit_context
        >>> from keel.accounts.models import KeelUser
        >>> with audit_context(user=KeelUser.objects.get(username='dokadmin')):
        ...     Application.objects.filter(pk=482).update(status='approved')

    Args:
        user: KeelUser instance. Must be authenticated for the audit gate
            to write rows (the signal handlers check ``user.is_authenticated``).
            Passing None is a no-op (matches the default cron behavior).
        ip: optional IP string. Defaults to '' (async work has no IP).
    """
    # Lazy-import to avoid circular: audit_signals doesn't depend on middleware.
    from keel.core.audit_signals import set_audit_context, get_audit_context

    prior_user, prior_ip = get_audit_context()
    set_audit_context(user=user, ip_address=ip)
    try:
        yield
    finally:
        set_audit_context(user=prior_user, ip_address=prior_ip)


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
    """Captures per-request audit metadata, logs login events, and
    populates thread-local context for signal-based auto-audit.

    After this middleware runs:
    - ``request.audit_ip`` is set to the client IP
    - ``keel.core.audit_signals.get_audit_context()`` returns the
      current user and IP for post_save/post_delete signal handlers
    """

    def __init__(self, get_response):
        self.get_response = get_response
        user_logged_in.connect(_handle_user_logged_in)

    def __call__(self, request):
        from keel.core.audit_signals import set_audit_context

        request.audit_ip = _get_client_ip(request)

        # Set thread-local context for signal-based audit logging
        user = getattr(request, 'user', None)
        if user and getattr(user, 'is_authenticated', False):
            set_audit_context(user=user, ip_address=request.audit_ip)
        else:
            set_audit_context(user=None, ip_address=request.audit_ip)

        try:
            response = self.get_response(request)
        finally:
            # Always clear thread-local context. Without try/finally, an
            # exception in view/downstream middleware would leak identity
            # to the next request served on the same thread.
            set_audit_context(user=None, ip_address=None)

        return response
