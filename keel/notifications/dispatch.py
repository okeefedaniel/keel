"""Unified notification dispatch.

This is the main entry point for sending notifications. It:
1. Looks up the notification type from the registry
2. Resolves recipients (explicit, role-based, or custom resolver)
3. Checks each recipient's channel preferences
4. Dispatches to each enabled channel
5. Optionally logs delivery results
"""
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model

from .channels import CHANNELS
from .registry import get_type

logger = logging.getLogger(__name__)


def notify(event, actor=None, recipients=None, context=None,
           title=None, message=None, link='', priority=None,
           channels=None, force=False):
    """Send a notification for an event.

    This is the primary API. Call it from views, signals, or services.

    Args:
        event: Registry key (e.g., 'application_submitted').
        actor: User who triggered the event (excluded from recipients).
        recipients: Explicit list of User instances. If None, auto-resolved
            from the NotificationType's role/resolver config.
        context: Dict of context data for templates and recipient resolution.
            Keys are available in email templates.
        title: Override the notification title. If None, uses the
            NotificationType label.
        message: Override the notification message. If None, uses a
            default based on the event label.
        link: URL path for the notification detail link.
        priority: Override priority. If None, uses the NotificationType default.
        channels: Override channels list. If None, uses registry defaults
            filtered by user preferences.
        force: If True, ignore user preferences and mute settings.
            Use for critical system notifications only.

    Returns:
        dict with keys:
            'sent': int — number of notifications sent
            'skipped': int — number skipped (muted/no channel)
            'errors': int — number of delivery errors
            'details': list of per-recipient results
    """
    context = context or {}

    # Look up the notification type
    ntype = get_type(event)
    if ntype is None:
        logger.warning('Unknown notification type: %s', event)
        # Still send if recipients and title are explicit
        if not recipients or not title:
            return {'sent': 0, 'skipped': 0, 'errors': 0, 'details': []}

    # Resolve defaults from registry
    _title = title or (ntype.label if ntype else event)
    _message = message or (ntype.description if ntype else '')
    _priority = priority or (ntype.priority if ntype else 'medium')
    _channels = channels or (ntype.default_channels if ntype else ['in_app'])

    # Auto-resolve link from link_template if no explicit link provided
    if not link and ntype and ntype.link_template:
        link = _resolve_link_template(ntype.link_template, context)

    # Resolve recipients
    if recipients is None:
        recipients = _resolve_recipients(ntype, context)

    # Exclude the actor (don't notify yourself)
    if actor:
        recipients = [r for r in recipients if r.pk != actor.pk]

    if not recipients:
        return {'sent': 0, 'skipped': 0, 'errors': 0, 'details': []}

    # Dispatch to each recipient
    results = {
        'sent': 0,
        'skipped': 0,
        'errors': 0,
        'details': [],
    }

    for recipient in recipients:
        recipient_result = _dispatch_to_recipient(
            recipient=recipient,
            event=event,
            ntype=ntype,
            title=_title,
            message=_message,
            link=link,
            priority=_priority,
            available_channels=_channels,
            context=context,
            force=force,
        )
        results['sent'] += recipient_result['sent']
        results['skipped'] += recipient_result['skipped']
        results['errors'] += recipient_result['errors']
        results['details'].append(recipient_result)

    return results


def _resolve_recipients(ntype, context):
    """Resolve recipients from the notification type config."""
    if ntype is None:
        return []

    # Custom resolver takes precedence
    if ntype.recipient_resolver:
        try:
            return list(ntype.recipient_resolver(context))
        except Exception:
            logger.exception(
                'Recipient resolver failed for %s', ntype.key,
            )
            return []

    # Role-based resolution
    if not ntype.default_roles:
        return []

    User = get_user_model()
    qs = User.objects.filter(is_active=True)

    if 'all' not in ntype.default_roles:
        # `role` on KeelUser is a per-request property, not a DB column —
        # it's stored on ProductAccess and resolved against the current
        # product. Filter through the relation, scoped to this product,
        # and dedupe with .distinct() since the join can fan out rows.
        from django.conf import settings
        product = (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower()
        qs = qs.filter(
            product_access__role__in=ntype.default_roles,
            product_access__is_active=True,
        )
        if product:
            qs = qs.filter(product_access__product=product)
        qs = qs.distinct()

    # Agency scoping
    if ntype.agency_scoped and ntype.agency_field:
        agency = _resolve_dotpath(context, ntype.agency_field)
        if agency:
            qs = qs.filter(agency=agency)

    return list(qs)


def _resolve_dotpath(context, path):
    """Resolve a dot-separated path from a context dict.

    E.g., 'application.grant_program.agency' looks up
    context['application'].grant_program.agency
    """
    parts = path.split('.')
    obj = context.get(parts[0])
    for part in parts[1:]:
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    return obj


def _resolve_link_template(template, context):
    """Resolve a link template string using the context dict.

    Supports dot-paths: ``'{application.pk}'`` resolves to
    ``context['application'].pk``.  If any placeholder can't be resolved,
    returns the empty string (no broken links).

    Examples:
        _resolve_link_template('/apps/{application.pk}/', {'application': app})
        # -> '/apps/42/'
    """
    import re

    def _replace(match):
        path = match.group(1)
        return str(_resolve_dotpath(context, path) or '')

    try:
        resolved = re.sub(r'\{([^}]+)\}', _replace, template)
        # If any placeholder resolved to empty, skip the link entirely
        if '//' in resolved.replace('://', '') or resolved.endswith('/None/'):
            return ''
        return resolved
    except Exception:
        logger.debug('Failed to resolve link template: %s', template, exc_info=True)
        return ''


def _dispatch_to_recipient(recipient, event, ntype, title, message, link,
                           priority, available_channels, context, force):
    """Send notification to a single recipient via their preferred channels."""
    result = {
        'recipient': str(recipient),
        'sent': 0,
        'skipped': 0,
        'errors': 0,
        'channels': {},
    }

    # Check user preferences (unless forced)
    if not force:
        pref = _get_user_preference(recipient, event)
    else:
        pref = None

    # Determine which channels to use
    if pref and pref.is_muted and not force:
        result['skipped'] = len(available_channels)
        return result

    for channel_name in available_channels:
        # Check preference for this channel
        if pref and not force:
            channel_enabled = getattr(pref, f'channel_{channel_name}', True)
            if not channel_enabled:
                result['skipped'] += 1
                result['channels'][channel_name] = 'skipped'
                continue

        dispatcher = CHANNELS.get(channel_name)
        if not dispatcher:
            logger.warning('Unknown channel: %s', channel_name)
            result['skipped'] += 1
            continue

        # Build channel-specific kwargs
        kwargs = {
            'recipient': recipient,
            'title': title,
            'message': message,
            'link': link,
            'priority': priority,
            'notification_type': event,
            'context': context,
        }

        # Add email-specific args
        if channel_name == 'email' and ntype:
            kwargs['email_template'] = ntype.email_template
            kwargs['email_subject'] = ntype.email_subject

        success, error = dispatcher(**kwargs)

        if success:
            result['sent'] += 1
            result['channels'][channel_name] = 'sent'
        else:
            result['errors'] += 1
            result['channels'][channel_name] = f'error: {error}'

        # Log delivery
        _log_delivery(recipient, event, channel_name, success, error)

    return result


def _get_user_preference(user, notification_type):
    """Look up a user's notification preference for a given type.

    Returns the preference object, or None if no preference is set
    (in which case registry defaults are used).
    """
    pref_model_path = getattr(
        settings, 'KEEL_NOTIFICATION_PREFERENCE_MODEL', None,
    )
    if not pref_model_path:
        return None

    try:
        PrefModel = apps.get_model(pref_model_path)
        return PrefModel.objects.filter(
            user=user,
            notification_type=notification_type,
        ).first()
    except Exception:
        return None


def _log_delivery(recipient, notification_type, channel, success, error):
    """Log a notification delivery attempt (if log model is configured)."""
    log_model_path = getattr(
        settings, 'KEEL_NOTIFICATION_LOG_MODEL', None,
    )
    if not log_model_path:
        return

    try:
        LogModel = apps.get_model(log_model_path)
        LogModel.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            channel=channel,
            success=success,
            error_message=error or '',
        )
    except Exception:
        logger.debug('Could not log notification delivery', exc_info=True)
