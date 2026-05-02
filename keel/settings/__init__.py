"""Suite-wide user settings page.

A registry-based "Settings" panel framework. Products extend
`SettingsPanel`, register panels in `AppConfig.ready()`, and they show
up automatically at `/settings/` with consistent chrome.

Pattern matches `keel.notifications` (notification type registry) and
`keel.foia.export` (FOIA-exportable type registry): one URL, one
shared template, panels light up only when the product registers them.

Usage in product `core/apps.py::ready()`:

    from keel.settings import register_panel
    from .settings_panels import MyProfilePanel
    register_panel(MyProfilePanel())

URLs in product `urls.py`:

    path('settings/', include('keel.settings.urls')),

End user lands at `/settings/` (the first visible panel renders), or
`/settings/<slug>/` for a specific panel. The avatar dropdown in
`keel/layouts/app.html` links to `{% url 'keel_settings:index' %}`.

Why this exists: prior to this module each product hand-rolled its own
profile / preferences pages (or had none, leaving users without a way
to see their API token, mailbox slug, or notification preferences). The
audit at docs/plans/bcc-email-ingest.md surfaced the gap.
"""
from .base import SettingsPanel
from .registry import register_panel, get_visible_panels, get_panel

__all__ = ['SettingsPanel', 'register_panel', 'get_visible_panels', 'get_panel']

default_app_config = 'keel.settings.apps.KeelSettingsConfig'
