"""Shared template tags for DockLabs products.

Provides sortable table headers, notification helpers, and common filters.
"""
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


# =========================================================================
# Filters
# =========================================================================

@register.filter
def dict_get(dictionary, key):
    """Look up a dictionary key in a template.

    Usage:
        {{ my_dict|dict_get:key_var }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def unread_count(user):
    """Return the unread notification count for a user.

    Usage:
        {{ request.user|unread_count }}
    """
    if not user or not user.is_authenticated:
        return 0
    for attr in ('notifications', 'core_notifications'):
        manager = getattr(user, attr, None)
        if manager is not None:
            return manager.filter(is_read=False).count()
    return 0


@register.filter
def role_badge(role):
    """Map a user role to a Bootstrap badge CSS class.

    Usage:
        <span class="badge {{ user.role|role_badge }}">{{ user.get_role_display }}</span>
    """
    mapping = {
        'admin': 'bg-danger',
        'system_admin': 'bg-danger',
        'agency_admin': 'bg-warning text-dark',
        'legislative_aid': 'bg-primary',
        'stakeholder': 'bg-info',
        'relationship_manager': 'bg-primary',
        'foia_officer': 'bg-success',
        'foia_attorney': 'bg-warning text-dark',
        'analyst': 'bg-secondary',
        'program_officer': 'bg-success',
        'fiscal_officer': 'bg-info',
        'grants_manager': 'bg-success',
        'reviewer': 'bg-info',
        'applicant': 'bg-secondary',
    }
    return mapping.get(role, 'bg-secondary')


# =========================================================================
# Tags
# =========================================================================


@register.simple_tag(takes_context=True)
def sortable_th(context, field, label, css_class=''):
    """Render a sortable <th> element with Bootstrap Icons.

    Works with keel.core.mixins.SortableListMixin which provides
    current_sort, current_dir, and filter_params in the template context.

    Usage:
        {% load keel_tags %}
        <tr>
            {% sortable_th 'name' 'Company Name' %}
            {% sortable_th 'created' 'Date Created' 'text-end' %}
        </tr>
    """
    current_sort = context.get('current_sort', '')
    current_dir = context.get('current_dir', 'asc')
    filter_params = context.get('filter_params', '')

    fp = f'&amp;{filter_params}' if filter_params else ''

    if current_sort == field and current_dir == 'asc':
        href = f'?sort={field}&amp;dir=desc{fp}'
        icon = '<i class="bi bi-sort-up-alt"></i>'
    elif current_sort == field and current_dir == 'desc':
        href = f'?sort={field}&amp;dir=asc{fp}'
        icon = '<i class="bi bi-sort-down"></i>'
    else:
        href = f'?sort={field}&amp;dir=asc{fp}'
        icon = '<i class="bi bi-chevron-expand"></i>'

    cls = f' {css_class}' if css_class else ''
    return format_html(
        '<th class="sortable-header{cls}">'
        '<a href="{href}">{label} {icon}</a>'
        '</th>',
        cls=mark_safe(cls),
        href=mark_safe(href),
        label=label,
        icon=mark_safe(icon),
    )


@register.simple_tag
def user_avatar(user, size=40):
    """Render *user*'s avatar at *size* px (default 40).

    Falls through ``avatar_html_for``: uploaded image → mirrored URL →
    inline initials SVG. The result is marked safe so the SVG renders
    inline; the helper escapes user-supplied strings (initials, label).

    Usage:

        {% load keel_tags %}
        {% user_avatar request.user 32 %}
        {% user_avatar collaborator 24 %}
    """
    if user is None or not getattr(user, 'is_authenticated', True):
        # Tag accepts an unauthenticated/None user (e.g. a comment
        # author whose KeelUser has been deactivated). Render a generic
        # placeholder rather than crashing.
        from types import SimpleNamespace
        user = SimpleNamespace(
            first_name='', last_name='', username='?', email='',
            avatar=None, avatar_url='', get_full_name=lambda: 'User',
        )
    from keel.core.avatars import avatar_html_for
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 40
    return mark_safe(avatar_html_for(user, size=size))


# =========================================================================
# Status dots — suite-wide visual treatment for status fields.
# See keel/CLAUDE.md "Status pills — default to text + dot" for the rule.
# =========================================================================

# Statuses that justify the filled exception variant. Anything else
# gets the calm dot+text treatment. Keep this list short — every
# addition is more shouting on the page.
EXCEPTION_STATUSES = frozenset({
    'urgent', 'overdue', 'needs_info', 'needs-info',
    'blocked', 'failed',
})


@register.simple_tag
def status_dot(value, label=None, exception=None):
    """Render a calm dot+label or filled exception pill for *value*.

    ``value`` is the status slug (e.g. ``"received"``, ``"needs_info"``).
    ``label`` defaults to the title-cased value with underscores/hyphens
    swapped for spaces. Pass ``exception=True`` / ``exception=False`` to
    override the auto-routing.

    Usage::

        {% load keel_tags %}
        {% status_dot record.status %}
        {% status_dot record.status "Awaiting review" %}
        {% status_dot "needs_info" exception=True %}
    """
    slug = (str(value) if value is not None else '').strip().lower()
    if not slug:
        return ''

    if label is None:
        label = slug.replace('_', ' ').replace('-', ' ').title()

    if exception is None:
        exception = slug in EXCEPTION_STATUSES

    base_class = 'dl-status-pill' if exception else 'dl-status-dot'
    # Normalize the modifier so both "needs_info" and "needs-info"
    # land on the same class hook (CSS declares both forms).
    modifier = slug.replace('_', '-')
    return format_html(
        '<span class="{base} {base}--{modifier}">{label}</span>',
        base=base_class,
        modifier=modifier,
        label=label,
    )


# =========================================================================
# AI feature gating
# =========================================================================

@register.simple_tag(takes_context=True)
def ai_state(context, product_code=None):
    """Return ``'off'``, ``'needs_key'``, or ``'ready'`` for the user.

    Usage::

        {% load keel_tags %}
        {% ai_state as state %}
        {% if state == 'ready' %}
          ...working AI surface...
        {% elif state == 'needs_key' %}
          {% include "keel/components/ai_key_prompt.html" %}
        {% endif %}

    Defaults the product code to ``settings.KEEL_PRODUCT_CODE``.
    Returns ``'off'`` when the user is anonymous.
    """
    from keel.core.ai_access import user_ai_state
    user = getattr(context.get('request'), 'user', None) or context.get('user')
    return user_ai_state(user, product_code)


@register.simple_tag(takes_context=True)
def can_use_ai(context, product_code=None):
    """Boolean variant of ``ai_state == 'ready'``.

    Usage::

        {% can_use_ai as ai_ready %}
        {% if ai_ready %}<button>Summarize</button>{% endif %}
    """
    from keel.core.ai_access import user_can_use_ai
    user = getattr(context.get('request'), 'user', None) or context.get('user')
    return user_can_use_ai(user, product_code)


@register.inclusion_tag(
    'keel/components/ai_key_prompt.html', takes_context=True,
)
def ai_key_prompt(context, product_code=None):
    """Render the "you have not yet put in your API key" prompt.

    No-op (renders nothing) unless the user is in ``'needs_key'`` state
    on this product. Templates can include this unconditionally and let
    the tag self-suppress when the prompt isn't applicable.

    Usage::

        {% load keel_tags %}
        {% ai_key_prompt %}
    """
    from keel.core.ai_access import user_ai_state
    request = context.get('request')
    user = getattr(request, 'user', None) or context.get('user')
    state = user_ai_state(user, product_code)
    return {
        'show': state == 'needs_key',
        'state': state,
        'settings_url': _ai_settings_url(),
        'request': request,
    }


def _ai_settings_url():
    """Where the user goes to set their API key.

    In suite mode this is Keel's ``/settings/?panel=ai``. In standalone
    mode this is the local ``/settings/?panel=ai``. Falls back to a
    blank string when the settings URL isn't wired (the prompt then
    renders the message without a link).
    """
    from django.conf import settings as django_settings
    from django.urls import NoReverseMatch, reverse
    from keel.core.utils import is_suite_mode

    if is_suite_mode():
        issuer = (getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or '').rstrip('/')
        if issuer:
            return f'{issuer}/settings/?panel=ai'
    try:
        return reverse('keel_settings:index') + '?panel=ai'
    except NoReverseMatch:
        return ''
