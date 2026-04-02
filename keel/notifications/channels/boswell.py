"""Boswell notification channel.

Sends a structured email to boswell@docklabs.ai so that the Boswell
AI assistant (running on OpenClaw) picks it up via its IMAP monitor
and forwards a formatted notification to Dan via Telegram.

When the notification is a change request, Boswell can launch Claude
Code in the correct product directory when Dan approves.
"""
import logging
import os

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

BOSWELL_EMAIL = 'boswell@docklabs.ai'


def send_boswell(recipient, title, message, link='', priority='medium',
                 notification_type='', context=None, **kwargs):
    """Send a notification to Boswell for Telegram delivery.

    The recipient arg is ignored — Boswell always delivers to Dan.
    The context dict may contain a 'change_request' key with the
    ChangeRequest instance for prompt generation.

    Returns:
        (success: bool, error_message: str)
    """
    context = context or {}
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@docklabs.ai')

    # Build the email body with structured sections
    sections = [
        f"NOTIFICATION TYPE: {notification_type}",
        f"PRIORITY: {priority}",
        f"TITLE: {title}",
        "",
        message,
    ]

    # If this is a change request, include full details + prompt
    change_request = context.get('change_request')
    if change_request:
        sections.append("")
        sections.append("--- CHANGE REQUEST DETAILS ---")
        sections.append(f"ID: {change_request.id}")
        sections.append(f"Product: {change_request.product}")
        sections.append(f"Category: {change_request.get_category_display()}")
        sections.append(f"Priority: {change_request.get_priority_display()}")
        sections.append(f"Submitted by: {change_request.submitted_by_name}")
        if change_request.submitted_by_email:
            sections.append(f"Email: {change_request.submitted_by_email}")
        if change_request.page_url:
            sections.append(f"Page: {change_request.page_url}")
        sections.append(f"\nDescription:\n{change_request.description}")

        # Generate the Claude Code prompt
        prompt = change_request.generate_prompt()
        sections.append("")
        sections.append("--- CLAUDE CODE PROMPT ---")
        sections.append(prompt)
        sections.append("--- END PROMPT ---")

    if link:
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost:8000')
        scheme = 'https' if 'localhost' not in domain else 'http'
        sections.append(f"\nAdmin link: {scheme}://{domain}{link}")

    # Instructions for Boswell
    sections.append("")
    sections.append("--- INSTRUCTIONS FOR BOSWELL ---")
    sections.append(
        "Send Dan a Telegram message summarizing this change request. "
        "Include: product, category, who submitted it, and their description. "
        "Tell Dan he can reply 'approve' to launch Claude Code with the prompt."
    )
    if change_request:
        sections.append("")
        sections.append("--- ON APPROVE ---")
        sections.append(
            "When Dan replies 'approve' (or similar affirmative), do the following:\n"
            f"1. Write the CLAUDE CODE PROMPT above to a temp file: /tmp/cr-{change_request.id}.md\n"
            f"2. Run: ~/dispatch/scripts/launch-claude-code.sh {change_request.product} /tmp/cr-{change_request.id}.md\n"
            "3. The script outputs 'tmux:<session>' on success.\n"
            "4. Tell Dan: 'Claude Code is running. Attach with: tmux attach -t <session>'"
        )

    body = "\n".join(sections)

    subject = f"[Keel] {title}"

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[BOSWELL_EMAIL],
            fail_silently=False,
        )
        return True, ''
    except Exception as e:
        logger.exception('Failed to send Boswell notification: %s', subject)
        return False, str(e)
