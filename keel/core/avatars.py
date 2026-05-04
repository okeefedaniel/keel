"""Avatar rendering helpers — uploaded image, fallback initials tile, Gravatar.

The canonical entry point is the ``user_avatar`` template tag in
``keel_tags``; this module implements the underlying logic so it can
also be called from views (e.g. emitting absolute URLs in JWT claims
or rendering avatars in PDF exports).

Resolution chain — see ``avatar_html_for(user, size)``:

1. ``user.avatar`` (uploaded ImageField) → that file's URL
2. ``user.avatar_url`` (mirrored from JWT picture claim) → that URL
3. Inline SVG initials tile, deterministic-color from username

Gravatar is intentionally NOT in the default chain. We don't want to
leak our users' email hashes to a third party on every page render,
and Gravatar's "mystery person" fallback doesn't match our visual
language. Products that explicitly want Gravatar can call
``gravatar_url(user, size)`` directly.
"""
from __future__ import annotations

import hashlib
from html import escape


# Color palette for the initials tile background. Picked for contrast
# with white text and visual diversity at thumbnail size. Order matters:
# the username's hash modulo len(palette) selects the entry, so the
# same user always gets the same color.
INITIALS_COLORS = (
    '#3b82f6',  # blue
    '#10b981',  # emerald
    '#f59e0b',  # amber
    '#8b5cf6',  # violet
    '#14b8a6',  # teal
    '#ef4444',  # red
    '#ec4899',  # pink
    '#6366f1',  # indigo
    '#84cc16',  # lime
    '#f97316',  # orange
)


def _initials_for(user) -> str:
    """Return the 1–2 letter initials for *user*.

    Prefers first+last name; falls back to first two letters of first
    name; ultimately falls back to the username. Always returns at
    least one uppercase ASCII character — the SVG looks awkward without
    a glyph in the center.
    """
    fn = (getattr(user, 'first_name', '') or '').strip()
    ln = (getattr(user, 'last_name', '') or '').strip()
    if fn and ln:
        return (fn[0] + ln[0]).upper()
    if fn:
        return fn[:2].upper()
    un = (getattr(user, 'username', '') or '').strip()
    if un:
        return un[:2].upper()
    return '?'


def _color_for(user) -> str:
    """Pick a palette color deterministically from the username."""
    seed = (getattr(user, 'username', '') or '?').encode('utf-8')
    # MD5 here is a short deterministic key, not a security hash;
    # usedforsecurity=False keeps Bandit + scanners quiet.
    h = hashlib.md5(seed, usedforsecurity=False).hexdigest()[:8]
    idx = int(h, 16) % len(INITIALS_COLORS)
    return INITIALS_COLORS[idx]


def initials_svg(user, size: int = 40) -> str:
    """Render an inline SVG initials tile.

    Returns a complete ``<svg>`` element as a string with ``width``,
    ``height``, and a ``role="img"`` ARIA hint. Includes ``aria-label``
    naming the user so screen readers announce something meaningful
    instead of "image".

    Designed to be drop-in for an ``<img>`` tag: render the SVG inline
    rather than as a data URL so the markup stays inspectable and
    color/text scale nicely with the surrounding zoom level.
    """
    initials = _initials_for(user)
    color = _color_for(user)
    label = (getattr(user, 'get_full_name', lambda: '')()
             or getattr(user, 'username', '') or 'User')
    # Font size = 42% of the tile. Empirically Poppins at this ratio
    # leaves enough margin and reads cleanly down to ~24 px tiles.
    font_size = int(size * 0.42)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="{escape(label)}">'
        f'<rect width="{size}" height="{size}" rx="{size // 2}" fill="{color}"/>'
        f'<text x="50%" y="50%" text-anchor="middle" '
        f'dominant-baseline="central" '
        f'font-family="Poppins, system-ui, -apple-system, sans-serif" '
        f'font-size="{font_size}" font-weight="600" fill="white">'
        f'{escape(initials)}</text></svg>'
    )


def gravatar_url(user, size: int = 80) -> str:
    """Build a Gravatar URL for *user*'s email.

    Returns a URL with ``d=mp`` (mystery person) so missing accounts
    render Gravatar's stock silhouette. Callers wanting our initials
    tile as the fallback should NOT use this helper — render the
    initials SVG directly via ``initials_svg`` and only use Gravatar
    when the user has explicitly opted in.

    Returns an empty string when the user has no email.
    """
    email = (getattr(user, 'email', '') or '').strip().lower()
    if not email:
        return ''
    # MD5 is the Gravatar protocol; not a security choice on our end.
    h = hashlib.md5(email.encode('utf-8'), usedforsecurity=False).hexdigest()
    return f'https://www.gravatar.com/avatar/{h}?s={int(size)}&d=mp'


def get_avatar_url(user) -> str:
    """Return the URL of *user*'s uploaded or mirrored avatar, or ''.

    Does NOT fall back to the initials SVG — the SVG is rendered inline
    by the template tag, not by URL. Use this when you specifically
    want a URL-typed result (JWT claims, JSON APIs, email templates).
    """
    avatar = getattr(user, 'avatar', None)
    if avatar:
        try:
            return avatar.url
        except (ValueError, AttributeError):
            # FileField raises ValueError when the file isn't actually
            # there but the FK was set to a stale name. Treat as absent.
            pass
    return getattr(user, 'avatar_url', '') or ''


def avatar_html_for(user, size: int = 40) -> str:
    """Return the HTML to render *user*'s avatar at *size* px.

    Used by the ``{% user_avatar %}`` template tag. Renders an ``<img>``
    when the user has an uploaded or mirrored avatar; renders the inline
    initials SVG otherwise. Always returns an HTML-safe string; callers
    should pass the result through ``mark_safe`` (the template tag does).
    """
    url = get_avatar_url(user)
    label = (getattr(user, 'get_full_name', lambda: '')()
             or getattr(user, 'username', '') or 'User')
    if url:
        return (
            f'<img src="{escape(url)}" alt="{escape(label)}" '
            f'width="{size}" height="{size}" '
            f'class="dl-avatar" style="border-radius:50%;object-fit:cover" '
            f'loading="lazy" decoding="async">'
        )
    return initials_svg(user, size=size)
