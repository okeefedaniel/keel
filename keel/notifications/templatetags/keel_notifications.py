"""Template tags for the Keel notification system."""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def notification_priority_icon(priority):
    """Render a Bootstrap icon for a notification priority level.

    Usage:
        {% load keel_notifications %}
        {% notification_priority_icon notification.priority %}
    """
    icons = {
        'low': '',
        'medium': '',
        'high': '<i class="bi bi-exclamation-circle text-warning me-1"></i>',
        'urgent': '<i class="bi bi-exclamation-triangle-fill text-danger me-1"></i>',
    }
    return mark_safe(icons.get(priority, ''))


@register.filter
def get_pref_attr(obj, attr):
    """Get an attribute from an object in a template.

    Used in the preferences template to navigate nested lookups:
        {{ preferences|get_pref_attr:ntype.key|get_pref_attr:"channel_email" }}
    """
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)
