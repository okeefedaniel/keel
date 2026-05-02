"""Base class for settings panels.

A panel is a self-contained section of the user-facing `/settings/`
page. Products register one or more panels in `AppConfig.ready()`.

Minimal contract:

    class MyPanel(SettingsPanel):
        slug = 'profile'
        label = 'Profile'
        icon = 'bi-person'
        order = 10                              # lower = earlier in nav

        def is_visible(self, user) -> bool:
            return user.is_authenticated         # default

        def get_context(self, request) -> dict:
            return {'form': MyForm(instance=request.user)}

        def post(self, request):                 # optional
            form = MyForm(request.POST, instance=request.user)
            if form.is_valid():
                form.save()
                return None  # framework adds success message + redirects
            return {'form': form}                # re-render with errors

The template at `templates/keel/settings/panels/<slug>.html` is rendered
inside the shared chrome and gets the dict returned by `get_context()`.
"""
from typing import Optional


class SettingsPanel:
    """Base class for a settings panel.

    Subclasses MUST set `slug` and `label`. Other class attrs are
    defaults; methods can be overridden for dynamic behavior.
    """

    # --- Class-level metadata ------------------------------------------
    slug: str = ''
    label: str = ''
    icon: str = 'bi-gear'  # Bootstrap icon class
    order: int = 100        # lower numbers float to the top of the nav
    description: str = ''   # optional one-line subtitle in the nav

    # --- Visibility ----------------------------------------------------
    def is_visible(self, user) -> bool:
        """Return True if this panel should appear in nav for `user`.

        Default: visible to any authenticated user. Override to gate by
        role, deployment, or installed-app presence.
        """
        return getattr(user, 'is_authenticated', False)

    # --- Rendering -----------------------------------------------------
    def get_template_name(self) -> str:
        return f'keel/settings/panels/{self.slug}.html'

    def get_context(self, request) -> dict:
        """Return template context for rendering this panel."""
        return {}

    # --- Form handling -------------------------------------------------
    def post(self, request) -> Optional[dict]:
        """Handle a POST submission against this panel.

        Return value semantics:
        - `None`  → success; framework adds a "Saved" message and
                    redirects back to the panel (PRG pattern).
        - `dict`  → re-render the panel with this dict as context (use
                    for displaying form errors).

        Default: 405-style no-op (framework returns "no action taken").
        """
        return None
