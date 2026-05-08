"""Template tags for the watcher / follow primitive.

Public surface (used by product detail templates):

    {% load follow_tags %}
    {% follow_button object %}                          {# default styling   #}
    {% follow_button object size="sm" %}                {# small variant     #}
    {% follow_button object label_following="Following" label_follow="Follow" %}

Renders a small button that toggles the current user's Watcher row for ``obj``.
Resolves ``KEEL_WATCHER_MODEL`` to determine the per-product Watcher table,
pre-checks the user's current follow state so the initial render is correct,
then ships htmx-style POST attrs the front-end JS uses to toggle on click.

Fail-soft by design: if KEEL_WATCHER_MODEL is unset, the tag renders empty.
Same for an unauthenticated request or ``obj is None``.
"""
from __future__ import annotations

import logging

from django import template
from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)
register = template.Library()


def _resolve_watcher_model():
    model_path = getattr(settings, 'KEEL_WATCHER_MODEL', None)
    if not model_path:
        return None
    try:
        return apps.get_model(model_path)
    except (LookupError, ValueError):
        logger.warning(
            'KEEL_WATCHER_MODEL=%s could not be resolved. follow_button rendering disabled.',
            model_path,
        )
        return None


@register.inclusion_tag(
    'keel/activity/_follow_button.html',
    takes_context=True,
)
def follow_button(
    context,
    obj,
    size: str = 'sm',
    label_following: str = 'Following',
    label_follow: str = 'Follow',
):
    """Render a follow/unfollow toggle button for ``obj``.

    Arguments:
        obj             -- the target record (any model with a PK)
        size            -- Bootstrap btn size suffix: '' / 'sm' / 'lg' (default 'sm')
        label_following -- label rendered when the user already follows (default 'Following')
        label_follow    -- label rendered when not yet following     (default 'Follow')

    Behaviour:
        * No KEEL_WATCHER_MODEL set       → renders nothing
        * Anonymous request               → renders nothing
        * obj is None                     → renders nothing
        * URL ``keel_activity:toggle_follow`` not mounted → renders nothing
                                            (silent fallback for legacy products)
        * Otherwise renders a Bootstrap button with htmx hooks
    """
    request = context.get('request')
    user = getattr(request, 'user', None) if request is not None else None
    if user is None or not getattr(user, 'is_authenticated', False) or obj is None:
        return {'enabled': False}

    Watcher = _resolve_watcher_model()
    if Watcher is None:
        return {'enabled': False}

    try:
        target_ct = ContentType.objects.get_for_model(type(obj))
    except Exception:
        logger.warning('follow_button: could not resolve ContentType for %r', obj, exc_info=True)
        return {'enabled': False}

    try:
        toggle_url = reverse('keel_activity:toggle_follow')
    except NoReverseMatch:
        # Product hasn't included keel.activity.urls yet — render nothing rather
        # than a button that posts to a nonexistent endpoint.
        return {'enabled': False}

    is_following = Watcher.objects.filter(
        user=user, target_ct=target_ct, target_id=str(obj.pk),
    ).exists()

    return {
        'enabled': True,
        'is_following': is_following,
        'target_ct_id': target_ct.pk,
        'target_id': str(obj.pk),
        'toggle_url': toggle_url,
        'size': size,
        'label_following': label_following,
        'label_follow': label_follow,
    }
