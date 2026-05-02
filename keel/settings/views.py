"""Views for the suite-wide /settings/ page.

URL contract:
    /settings/              → index; redirects to first visible panel
    /settings/<slug>/       → that panel's content rendered inside the
                              shared chrome (left rail of all visible
                              panels, right pane is panel-specific)

POST flows go to /settings/<slug>/. The panel's `.post(request)`
returns either None (success → PRG redirect with success message) or a
dict (re-render with that context — used for form errors).
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .registry import get_panel, get_visible_panels

logger = logging.getLogger(__name__)


def _shared_context(request, active_slug: str) -> dict:
    panels = get_visible_panels(request.user)
    return {
        'panels': panels,
        'active_slug': active_slug,
        'active_panel': next((p for p in panels if p.slug == active_slug), None),
    }


@login_required
def settings_index(request):
    """Default landing — redirect to the first visible panel.

    Returning a redirect rather than rendering keeps the URL bar at the
    canonical panel URL, which is bookmarkable.
    """
    panels = get_visible_panels(request.user)
    if not panels:
        # Edge case: no panels registered (a deployment with neither
        # keel.notifications nor any product panels). Render an empty
        # state rather than 404 — the page is the answer to "where do
        # I find my settings?" and a 404 here is confusing.
        return render(request, 'keel/settings/empty.html', status=200)
    return HttpResponseRedirect(
        reverse('keel_settings:panel', kwargs={'slug': panels[0].slug})
    )


@login_required
@require_http_methods(['GET', 'POST'])
def settings_panel(request, slug: str):
    panel = get_panel(slug)
    if panel is None or not panel.is_visible(request.user):
        # Don't disclose registered-but-hidden panels.
        return render(request, 'keel/settings/not_found.html', status=404)

    if request.method == 'POST':
        result = panel.post(request)
        if result is None:
            messages.success(request, f'{panel.label} updated.')
            return HttpResponseRedirect(
                reverse('keel_settings:panel', kwargs={'slug': slug})
            )
        # Form errors path — re-render with what panel.post() returned.
        ctx = _shared_context(request, slug)
        ctx.update(result)
        return render(request, 'keel/settings/index.html', ctx, status=400)

    ctx = _shared_context(request, slug)
    ctx.update(panel.get_context(request))
    return render(request, 'keel/settings/index.html', ctx)
