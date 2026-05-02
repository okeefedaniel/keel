"""Panel registry for keel.settings.

Module-level dict; products register at import time via
`AppConfig.ready()`. Same pattern as `keel.notifications.registry` and
`keel.foia.export`.
"""
import logging

from .base import SettingsPanel

logger = logging.getLogger(__name__)

# slug → SettingsPanel instance
_PANELS: dict[str, SettingsPanel] = {}


def register_panel(panel: SettingsPanel) -> None:
    """Register a panel for the user-settings page.

    Idempotent — re-registering the same slug overwrites the prior
    registration. (Useful in dev with autoreload; tests should call
    `_clear_panels()` between cases for isolation.)
    """
    if not getattr(panel, 'slug', ''):
        raise ValueError(f'SettingsPanel must define `slug`; got {panel!r}')
    if not getattr(panel, 'label', ''):
        raise ValueError(f'SettingsPanel `{panel.slug}` must define `label`')
    if panel.slug in _PANELS and _PANELS[panel.slug] is not panel:
        logger.debug('settings: panel slug=%r re-registered (overwriting)', panel.slug)
    _PANELS[panel.slug] = panel


def get_panel(slug: str) -> SettingsPanel | None:
    return _PANELS.get(slug)


def get_visible_panels(user) -> list[SettingsPanel]:
    """Return the list of panels visible to `user`, sorted by `order`
    then `label`."""
    visible = [p for p in _PANELS.values() if p.is_visible(user)]
    return sorted(visible, key=lambda p: (p.order, p.label))


def _clear_panels() -> None:
    """Test helper — wipe the registry. Do not call from product code."""
    _PANELS.clear()
