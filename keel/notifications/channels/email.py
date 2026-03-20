"""Email notification channel."""
import logging
import os

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def build_absolute_url(path):
    """Build a fully-qualified URL from a relative path.

    Uses RAILWAY_PUBLIC_DOMAIN in production, falls back to localhost.
    """
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost:8000')
    scheme = 'https' if 'localhost' not in domain else 'http'
    return f'{scheme}://{domain}{path}'


def send_email(recipient, title, message, link='', priority='medium',
               notification_type='', email_template=None, email_subject=None,
               context=None, **kwargs):
    """Send an email notification.

    If email_template is provided, renders it as HTML with context.
    Otherwise, sends a plain-text email with the message body.

    Args:
        recipient: User instance (must have .email attribute).
        title: Notification title (used as subject fallback).
        message: Plain text message body.
        link: URL path to include in the email.
        priority: Priority level.
        notification_type: Registry key.
        email_template: Optional HTML template path.
        email_subject: Optional subject override. Can include {title}.
        context: Optional template context dict.

    Returns:
        (success: bool, error_message: str)
    """
    email_addr = getattr(recipient, 'email', None)
    if not email_addr:
        return False, 'Recipient has no email address'

    subject = email_subject.format(title=title) if email_subject else title
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@docklabs.ai')

    # Build template context
    ctx = {
        'recipient': recipient,
        'title': title,
        'message': message,
        'link': link,
        'absolute_link': build_absolute_url(link) if link else '',
        'priority': priority,
        'site_name': getattr(settings, 'KEEL_PRODUCT_NAME', 'DockLabs'),
    }
    if context:
        ctx.update(context)

    try:
        if email_template:
            html_body = render_to_string(email_template, ctx)
            # Auto-discover plain text version
            txt_template = email_template.rsplit('.', 1)[0] + '.txt'
            try:
                text_body = render_to_string(txt_template, ctx)
            except Exception:
                text_body = message
        else:
            # No template — use the generic notification email
            try:
                html_body = render_to_string(
                    'notifications/emails/generic.html', ctx,
                )
                text_body = render_to_string(
                    'notifications/emails/generic.txt', ctx,
                )
            except Exception:
                # Absolute fallback — plain text only
                html_body = None
                text_body = message
                if link:
                    text_body += f'\n\nView details: {build_absolute_url(link)}'

        send_mail(
            subject=subject,
            message=text_body,
            from_email=from_email,
            recipient_list=[email_addr],
            html_message=html_body,
            fail_silently=False,
        )
        return True, ''

    except Exception as e:
        logger.exception(
            'Failed to send email to %s (subject: %s)', email_addr, subject,
        )
        return False, str(e)
