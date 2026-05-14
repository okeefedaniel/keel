"""Template tags for keel.activity.

Public surface (used by product detail templates):

    {% load activity_tags %}
    {% activity_panel object %}                           {# default 25 entries #}
    {% activity_panel object limit=10 %}
    {% activity_panel object limit=10 title="Project History" %}

Renders the shared partial at keel/activity/_panel.html with the per-record
activity feed visible to the current user. Resolves the concrete Activity
model from settings.KEEL_ACTIVITY_MODEL (set per product in settings.py),
filters by the GFK target == ``obj``, applies ``Activity.visible_to(user)``,
slices to ``limit``, and renders.

Fail-soft by design: if KEEL_ACTIVITY_MODEL is unset (a product that hasn't
adopted keel.activity yet, or a bare keel-only deploy), the tag renders
nothing rather than raising. Same for an unauthenticated request.
"""
from __future__ import annotations

import logging

from django import template
from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)
register = template.Library()


def _resolve_activity_model():
    """Look up the concrete Activity model from settings, or None if unset/bad."""
    model_path = getattr(settings, 'KEEL_ACTIVITY_MODEL', None)
    if not model_path:
        return None
    try:
        return apps.get_model(model_path)
    except (LookupError, ValueError):
        logger.warning(
            'KEEL_ACTIVITY_MODEL=%s could not be resolved. activity_panel rendering disabled.',
            model_path,
        )
        return None


@register.inclusion_tag(
    'keel/activity/_panel.html',
    takes_context=True,
)
def activity_panel(context, obj, limit: int = 25, title: str = 'Recent Activity', more_url: str = ''):
    """Render the activity panel for ``obj`` filtered to entries the current user can see.

    Arguments:
        obj      -- the target record (any model with an integer or UUID PK)
        limit    -- max entries to render (default 25)
        title    -- card header label (default "Recent Activity")
        more_url -- optional URL for a "View all" link in the header

    Behaviour:
        * No KEEL_ACTIVITY_MODEL set       → renders empty (no card chrome)
        * Anonymous request                → renders empty
        * obj is None                      → renders empty
        * Activity.visible_to fails        → log + render empty
        * Otherwise renders Activity.render_for(user) for each visible row
    """
    request = context.get('request')
    user = getattr(request, 'user', None) if request is not None else None
    if user is None or not getattr(user, 'is_authenticated', False) or obj is None:
        return {'activity_entries': [], 'activity_title': title, 'activity_more_url': more_url}

    Activity = _resolve_activity_model()
    if Activity is None:
        return {'activity_entries': [], 'activity_title': title, 'activity_more_url': more_url}

    try:
        target_ct = ContentType.objects.get_for_model(type(obj))
    except Exception:
        logger.warning('activity_panel: could not resolve ContentType for %r', obj, exc_info=True)
        return {'activity_entries': [], 'activity_title': title, 'activity_more_url': more_url}

    # select_related('actor', 'target_ct'): actor is dereferenced via str() in
    # render_for; target_ct is dereferenced if a subclass overrides render_for
    # to expose self.target. Defensive even though the base render_for no
    # longer returns target — keeps the abstraction safe for product overrides.
    qs = Activity.objects.filter(target_ct=target_ct, target_id=str(obj.pk)).select_related('actor', 'target_ct')

    try:
        qs = Activity.visible_to(user, queryset=qs)
    except NotImplementedError:
        logger.warning(
            '%s.visible_to is not implemented. activity_panel rendering empty.',
            Activity.__name__,
        )
        return {'activity_entries': [], 'activity_title': title, 'activity_more_url': more_url}
    except Exception:
        logger.warning('activity_panel: visible_to raised for %r', obj, exc_info=True)
        return {'activity_entries': [], 'activity_title': title, 'activity_more_url': more_url}

    rows = list(qs.order_by('-created_at')[:int(limit)])
    entries = [row.render_for(user) for row in rows]
    return {
        'activity_entries': entries,
        'activity_title': title,
        'activity_more_url': more_url,
    }
