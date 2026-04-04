"""
HTML sanitization for inbound email content.

External email HTML can contain arbitrary CSS, JavaScript, tracking pixels,
and other hostile content. This module strips it down to safe, renderable
HTML before it's displayed in the comms panel.

Uses a lightweight regex-based approach with no external dependencies.
For production deployments handling high-risk content, install nh3 or
bleach for more robust parsing.
"""
import re

# Tags allowed in rendered email content
ALLOWED_TAGS = frozenset({
    'p', 'br', 'div', 'span',
    'strong', 'b', 'em', 'i', 'u', 's',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'img',
    'blockquote', 'pre', 'code',
    'hr',
})

# Attributes allowed per tag (all others stripped)
ALLOWED_ATTRS = {
    'a': {'href', 'title'},
    'img': {'src', 'alt', 'width', 'height'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}

# Patterns for stripping dangerous content
SCRIPT_RE = re.compile(r'<script[^>]*>.*?</script>', re.DOTALL | re.IGNORECASE)
STYLE_RE = re.compile(r'<style[^>]*>.*?</style>', re.DOTALL | re.IGNORECASE)
COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
EVENT_ATTR_RE = re.compile(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)
STYLE_ATTR_RE = re.compile(r'\s+style\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)
TAG_RE = re.compile(r'<(/?)(\w+)([^>]*)(/?)>', re.IGNORECASE)
ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
JAVASCRIPT_URI_RE = re.compile(r'^\s*javascript:', re.IGNORECASE)
DATA_URI_RE = re.compile(r'^\s*data:', re.IGNORECASE)


def sanitize_html(html: str) -> str:
    """Strip dangerous HTML from inbound email content.

    Removes scripts, styles, event handlers, and non-allowlisted tags.
    Links with javascript: URIs are defanged. Returns safe HTML suitable
    for rendering inside the comms panel.
    """
    if not html:
        return ''

    # Strip scripts, styles, and comments entirely
    html = SCRIPT_RE.sub('', html)
    html = STYLE_RE.sub('', html)
    html = COMMENT_RE.sub('', html)

    # Strip event handler attributes (onclick, onload, etc.)
    html = EVENT_ATTR_RE.sub('', html)

    # Strip inline styles (can leak data via url(), expression(), etc.)
    html = STYLE_ATTR_RE.sub('', html)

    def replace_tag(match):
        closing = match.group(1)
        tag_name = match.group(2).lower()
        attrs_str = match.group(3)
        self_closing = match.group(4)

        if tag_name not in ALLOWED_TAGS:
            return ''

        # Filter attributes
        allowed = ALLOWED_ATTRS.get(tag_name, set())
        clean_attrs = []
        if attrs_str and allowed:
            for attr_match in ATTR_RE.finditer(attrs_str):
                attr_name = attr_match.group(1).lower()
                attr_value = attr_match.group(2) or attr_match.group(3) or attr_match.group(4) or ''

                if attr_name not in allowed:
                    continue

                # Block javascript: and data: URIs in href/src
                if attr_name in ('href', 'src'):
                    if JAVASCRIPT_URI_RE.match(attr_value) or DATA_URI_RE.match(attr_value):
                        continue

                clean_attrs.append(f'{attr_name}="{attr_value}"')

        # Add target="_blank" and rel="noopener" to links
        if tag_name == 'a' and not closing:
            clean_attrs.extend(['target="_blank"', 'rel="noopener noreferrer"'])

        attrs_part = (' ' + ' '.join(clean_attrs)) if clean_attrs else ''
        slash = '/' if self_closing else ''

        return f'<{closing}{tag_name}{attrs_part}{slash}>'

    return TAG_RE.sub(replace_tag, html)
