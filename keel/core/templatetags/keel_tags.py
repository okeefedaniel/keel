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
