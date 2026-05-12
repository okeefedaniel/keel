"""Template tags for /audit/.

* ``filter_link`` — wrap a cell value in an <a> that adds the dimension
  to the current querystring (click-to-filter).
* ``audit_deep_link`` — render an entity column either as a link via
  ``deep_link_snapshot`` (when present + scheme allowlisted) or as plain
  text. The scheme allowlist closes the stored-XSS surface flagged by the
  eng review (decision A1).
"""
from __future__ import annotations

from urllib.parse import urlencode, urlsplit

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from keel_site.audit.permissions import can_view_audit as _can_view_audit

register = template.Library()


@register.simple_tag
def can_view_audit(user):
    """Bool: should this user see /audit/ (and the sidebar link)?

    Same gate as the view itself, so the sidebar item matches the view's
    permission check (no orphan link for users who'd 403).
    """
    return _can_view_audit(user)

_ALLOWED_SCHEMES = ('http', 'https')


@register.simple_tag(takes_context=True)
def filter_url(context, dimension: str, value: str) -> str:
    """Return a bare URL that filters the current page to dimension=value.

    Use this when you need to put the URL into an attribute (chip href,
    pagination, etc.). For inline click-to-filter cells use ``filter_link``.
    """
    if not value:
        return ''
    request = context['request']
    qs = request.GET.copy()
    qs.pop('page', None)
    qs.setlist(dimension, [value])
    return '?' + qs.urlencode()


@register.simple_tag(takes_context=True)
def filter_link(context, dimension: str, value: str):
    """Render <a href="?dimension=value&..."> with the value as link text."""
    if not value:
        return ''
    href = filter_url(context, dimension, value)
    return format_html('<a href="{}" class="audit-cell-link">{}</a>', href, value)


@register.simple_tag
def audit_deep_link(entry: dict):
    """Render entity_type+entity_id as a link via ``deep_link_snapshot``.

    The scheme is allowlisted to http(s) or leading slash to defeat
    ``javascript:`` payloads injected via a buggy or malicious product
    audit emitter (review decision A1).
    """
    label_type = entry.get('entity_type') or ''
    label_id = entry.get('entity_id') or ''
    label = f'{label_type} {label_id}'.strip()
    if not label:
        return ''
    url = (entry.get('deep_link_snapshot') or '').strip()
    if url and _is_safe_url(url):
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
            url, label,
        )
    return escape(label)


def _is_safe_url(url: str) -> bool:
    # Reject protocol-relative URLs (//evil.com/x) — they inherit the
    # page scheme and route to an arbitrary host.
    if url.startswith('//'):
        return False
    if url.startswith('/'):
        return True
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in _ALLOWED_SCHEMES
