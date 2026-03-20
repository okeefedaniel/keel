"""Template tags for the change request submission widget.

Usage in any product template:

    {% load keel_requests %}
    {% request_widget %}

Renders a floating feedback button + modal form that POSTs to the
submit endpoint. Only shown to authenticated users.
"""
from django import template
from django.conf import settings

register = template.Library()


@register.inclusion_tag('requests/widget.html', takes_context=True)
def request_widget(context):
    """Render the feedback submission widget."""
    request = context.get('request')
    user = getattr(request, 'user', None)
    return {
        'user': user,
        'is_authenticated': user and user.is_authenticated,
        'product': getattr(settings, 'KEEL_PRODUCT_NAME', ''),
        'csrf_token': context.get('csrf_token'),
    }
