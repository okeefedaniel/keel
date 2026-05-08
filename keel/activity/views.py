"""Watcher toggle endpoint for keel.activity.

Single POST view that creates or deletes a Watcher row for the current user
against an arbitrary target (resolved by content-type id + object id).
Used by the ``{% follow_button %}`` template tag, which posts via fetch / htmx.

Mounted via ``include('keel.activity.urls')`` in each product's urls.py:

    urlpatterns = [
        ...
        path('activity/', include('keel.activity.urls')),
    ]

Endpoints:
    POST /activity/follow/toggle/  -- toggle follow on (target_ct_id, target_id)

Auth: login required. Anonymous requests get 401.
"""
from __future__ import annotations

import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def _resolve_watcher_model():
    """Resolve the per-product Watcher concrete model. None if unset/unresolvable."""
    model_path = getattr(settings, 'KEEL_WATCHER_MODEL', None)
    if not model_path:
        return None
    try:
        return apps.get_model(model_path)
    except (LookupError, ValueError):
        logger.warning(
            'KEEL_WATCHER_MODEL=%s could not be resolved. Follow toggle disabled.',
            model_path,
        )
        return None


@require_POST
@login_required
def toggle_follow(request):
    """Toggle the current user's Watcher row for the given target.

    POST data:
        target_ct_id -- ContentType.pk for the target model (required)
        target_id    -- the target's primary key as a string (required)

    Returns JSON: ``{"following": bool, "watcher_id": str|null}``.

    Idempotent: if a Watcher row already exists, deletes it (unfollow). If not,
    creates one. The unique-together constraint on (user, target_ct, target_id)
    means racing requests can't create duplicates.
    """
    Watcher = _resolve_watcher_model()
    if Watcher is None:
        return JsonResponse(
            {'error': 'Follow disabled — KEEL_WATCHER_MODEL not configured.'},
            status=503,
        )

    target_ct_id = (request.POST.get('target_ct_id') or '').strip()
    target_id = (request.POST.get('target_id') or '').strip()
    if not target_ct_id or not target_id:
        return HttpResponseBadRequest('target_ct_id and target_id are required.')

    try:
        target_ct_id_int = int(target_ct_id)
    except ValueError:
        return HttpResponseBadRequest('target_ct_id must be an integer.')

    try:
        ct = ContentType.objects.get_for_id(target_ct_id_int)
    except ContentType.DoesNotExist:
        return HttpResponseBadRequest('Unknown target_ct_id.')

    # Resolve the target so we can validate it exists. This guards against
    # follow rows pointing at deleted records (cheap query — usually 1 row).
    target_model = ct.model_class()
    if target_model is None:
        return HttpResponseBadRequest('Target ContentType has no model class.')
    if not target_model.objects.filter(pk=target_id).exists():
        return HttpResponseBadRequest('Target record not found.')

    existing = Watcher.objects.filter(
        user=request.user, target_ct=ct, target_id=target_id,
    ).first()

    if existing is not None:
        existing.delete()
        return JsonResponse({'following': False, 'watcher_id': None})

    watcher = Watcher.objects.create(
        user=request.user, target_ct=ct, target_id=target_id,
    )
    return JsonResponse({'following': True, 'watcher_id': str(watcher.pk)})
