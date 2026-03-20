"""Template tags for Keel demo login buttons."""
from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

from keel.core.demo import get_demo_roles, get_role_display

register = template.Library()


@register.simple_tag(takes_context=True)
def demo_login_buttons(context):
    """Render one-click demo login buttons.

    Usage in any DockLabs login template:
        {% load keel_demo %}
        {% demo_login_buttons %}

    Only renders when DEMO_MODE is True.
    Requires a URL named 'demo_login' to be configured.
    """
    if not getattr(settings, 'DEMO_MODE', False):
        return ''

    request = context.get('request')
    if request and request.user.is_authenticated:
        return ''

    roles = get_demo_roles()
    if not roles:
        return ''

    # Get CSRF token
    csrf_token = context.get('csrf_token', '')

    buttons_html = []
    for role in roles:
        display = get_role_display(role)
        buttons_html.append(f'''
        <form method="post" action="/demo-login/" class="d-inline">
            <input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">
            <input type="hidden" name="role" value="{role}">
            <button type="submit" class="btn btn-outline-{display['color']} btn-sm">
                <i class="bi {display['icon']} me-1"></i>{display['label']}
            </button>
        </form>''')

    buttons = '\n'.join(buttons_html)
    return mark_safe(f'''
    <div class="demo-login-section mt-4 pt-3 border-top">
        <p class="text-muted small text-center mb-2">
            <i class="bi bi-play-circle me-1"></i>Quick Demo Login
        </p>
        <div class="d-flex flex-wrap gap-2 justify-content-center">
            {buttons}
        </div>
    </div>''')
