"""Template tags for the change request submission widget.

Usage in any product template:

    {% load keel_requests %}
    {% request_widget %}

Renders a floating feedback button + modal form that POSTs to the
submit endpoint. Only shown to beta testers and admins.
"""
import logging

from django import template
from django.conf import settings

register = template.Library()
logger = logging.getLogger(__name__)



@register.inclusion_tag('requests/widget.html', takes_context=True)
def request_widget(context):
    """Render the feedback submission widget."""
    request = context.get('request')
    user = getattr(request, 'user', None)
    product = getattr(settings, 'KEEL_PRODUCT_NAME', '')

    show_widget = False
    if user and user.is_authenticated:
        if user.is_superuser:
            show_widget = True
        else:
            try:
                from keel.accounts.models import ProductAccess
                from django.db.models import Q
                show_widget = ProductAccess.objects.filter(
                    user=user, product=product, is_active=True,
                ).filter(
                    Q(is_beta_tester=True) | Q(role__in=('admin', 'system_admin'))
                ).exists()
            except Exception:
                show_widget = getattr(user, '_is_beta_tester', False)

    return {
        'user': user,
        'show_widget': show_widget,
        'product': product,
        'csrf_token': context.get('csrf_token'),
    }
