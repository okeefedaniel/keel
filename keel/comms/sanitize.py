"""
HTML sanitization for inbound email content.

External email HTML can contain arbitrary CSS, JavaScript, tracking pixels,
and other hostile content. This module strips it down to safe, renderable
HTML before it's displayed in the comms panel.

Backed by ``nh3`` (Rust-backed ammonia) — a parser-based sanitizer that is
resilient to mutation-XSS and attribute-splitting tricks that the prior
regex-based pass could be fooled by.
"""
import nh3

# Tags allowed in rendered email content
ALLOWED_TAGS = {
    'p', 'br', 'div', 'span',
    'strong', 'b', 'em', 'i', 'u', 's',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'img',
    'blockquote', 'pre', 'code',
    'hr',
}

# Attributes allowed per tag (all others stripped)
ALLOWED_ATTRS = {
    'a': {'href', 'title', 'target', 'rel'},
    'img': {'src', 'alt', 'width', 'height'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}

_ALLOWED_URL_SCHEMES = {'http', 'https', 'mailto', 'tel'}


def sanitize_html(html: str) -> str:
    """Strip dangerous HTML from inbound email content.

    Uses nh3 with a conservative tag + attribute allowlist. Scripts, styles,
    event handlers, and non-allowlisted tags are removed. Links are limited
    to safe URL schemes.
    """
    if not html:
        return ''

    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        url_schemes=_ALLOWED_URL_SCHEMES,
        link_rel='noopener noreferrer',
        strip_comments=True,
    )


def strip_all_html(html: str) -> str:
    """Aggressively strip every tag — return plain text only.

    Use for any content that will be rendered inside templates that already
    mark it |safe (e.g. Claude-generated summaries).
    """
    if not html:
        return ''
    return nh3.clean(html, tags=set(), attributes={})
