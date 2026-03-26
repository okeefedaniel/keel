"""FOIA template tags — export button for agency staff."""
from django import template

register = template.Library()

# Roles that can see the FOIA export button
FOIA_ROLES = {
    'foia_attorney', 'foia_officer', 'foia_manager',
    'agency_admin', 'system_admin', 'admin',
}


def _user_can_export(user):
    """Check if the user has a FOIA-capable role."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    role = getattr(user, 'role', None)
    if role and role in FOIA_ROLES:
        return True
    if hasattr(user, 'product_access'):
        return user.product_access.filter(
            role__in=FOIA_ROLES, is_active=True,
        ).exists()
    return False


@register.inclusion_tag('keel/foia/_export_button.html', takes_context=True)
def foia_export_button(context, record, record_type, product_name):
    """Render a FOIA export button. Only visible to authorized roles.

    Usage:
        {% load foia_tags %}
        {% foia_export_button testimony "testimony" "lookout" %}
    """
    request = context.get('request')
    user = request.user if request else None

    return {
        'show_button': _user_can_export(user),
        'record_id': str(record.pk) if hasattr(record, 'pk') else str(record),
        'record_type': record_type,
        'product_name': product_name,
        'record_title': getattr(record, 'title', getattr(record, '__str__', lambda: '')()),
    }
