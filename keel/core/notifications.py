"""Shared notification infrastructure for DockLabs products.

**MIGRATION NOTE (Keel v0.6.0):** This module is the backward-compatible
low-level API. For new code, prefer ``keel.notifications.notify()`` which
provides event-driven dispatch with user preferences and multi-channel
support. These helpers are still used internally by the channel dispatchers.

Provides three reusable helpers:

1. ``build_absolute_url(path)`` — Railway-aware URL builder
2. ``send_notification_email(...)`` — HTML+text multipart email sender
3. ``create_notification(...)`` — In-app notification record creator

Usage:
    # NEW (preferred) — event-driven with preferences:
    from keel.notifications import notify
    notify(event='application_submitted', actor=request.user,
           context={'application': app}, link=f'/applications/{app.pk}/')

    # LEGACY (still works) — direct low-level:
    from keel.core.notifications import (
        build_absolute_url, send_notification_email, create_notification,
    )
    create_notification(recipient=user, title='...', message='...', link='/')

Requires KEEL_NOTIFICATION_MODEL in settings (e.g., 'core.Notification').
Falls back to KEEL_AUDIT_LOG_MODEL's app label + '.Notification' if not set.
"""
import logging
import os

from django.apps import apps
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _get_notification_model():
    """Resolve the Notification model from settings."""
    model_path = getattr(settings, 'KEEL_NOTIFICATION_MODEL', None)
    if model_path:
        return apps.get_model(model_path)
    # Fallback: assume same app_label as the audit log model
    audit_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    app_label = audit_path.split('.')[0]
    return apps.get_model(f'{app_label}.Notification')


def build_absolute_url(path):
    """Build a fully-qualified URL from a path.

    Uses ``RAILWAY_PUBLIC_DOMAIN`` in production (Railway deployments),
    falls back to ``localhost:8000`` for local development.
    """
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost:8000')
    scheme = 'https' if 'localhost' not in domain else 'http'
    return f'{scheme}://{domain}{path}'


def send_notification_email(recipient_email, subject, template_name, context):
    """Render an HTML email template and send it. Fails silently with logging.

    Automatically looks for a matching ``.txt`` template (same base name) to
    use as the plain-text body. This multipart approach improves
    deliverability and prevents emails from being flagged as spam.
    """
    try:
        html_body = render_to_string(template_name, context)
        # Derive plain-text template path from the HTML template name
        txt_template = template_name.rsplit('.', 1)[0] + '.txt'
        try:
            text_body = render_to_string(txt_template, context)
        except Exception:
            text_body = ''
        send_mail(
            subject=subject,
            message=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_body,
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            'Failed to send notification email to %s (subject: %s)',
            recipient_email, subject,
        )


def create_notification(recipient, title, message, link='', priority='medium'):
    """Create an in-app Notification record.

    Returns the created Notification instance, or None on failure.
    """
    try:
        Notification = _get_notification_model()
        return Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            link=link,
            priority=priority,
        )
    except Exception:
        logger.exception('Failed to create notification for %s', recipient)
        return None
