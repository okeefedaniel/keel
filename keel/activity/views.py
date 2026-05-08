"""Watcher toggle + per-record category filter endpoints for keel.activity.

Used by the ``{% follow_button %}`` template tag and its dropdown variant.

Mounted via ``include('keel.activity.urls')`` in each product's urls.py:

    urlpatterns = [
        ...
        path('activity/', include('keel.activity.urls')),
    ]

Endpoints:
    POST /activity/follow/toggle/      -- toggle follow on (target_ct_id, target_id)
    POST /activity/follow/categories/  -- set notify_verbs from a list of verb-category
                                          keys (per-record granularity).

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


# ---------------------------------------------------------------------------
# Verb categories — group the 48 verbs in VERB_CATALOG into a small,
# user-meaningful set for the per-record dropdown UI.
#
# Categories are namespace-prefix-driven; lifecycle verbs split between
# 'workflow' (archive/unarchive, the things users care about) and admin/system
# events that we don't expose as togglable rows.
# ---------------------------------------------------------------------------
CATEGORY_LABELS = {
    'workflow':    'Status changes',
    'collab':      'Collaborator changes',
    'diligence':   'Notes & attachments',
    'signing':     'Signing events',
    'interaction': 'Interactions',
    'cross':       'Cross-product events',
}

# Map category → set of verb codes.  Built lazily so VERB_CATALOG import order
# can't bite us (verbs.py imports cleanly with no Django dependency).
_VERBS_BY_CATEGORY: dict[str, set[str]] = {}


def _verbs_by_category() -> dict[str, set[str]]:
    """Lazy-build CATEGORY → {verb codes} mapping from VERB_CATALOG."""
    global _VERBS_BY_CATEGORY
    if _VERBS_BY_CATEGORY:
        return _VERBS_BY_CATEGORY
    from keel.activity.verbs import VERB_CATALOG
    by_cat: dict[str, set[str]] = {key: set() for key in CATEGORY_LABELS}
    for code in VERB_CATALOG:
        ns, _, _rest = code.partition('.')
        if ns == 'lifecycle' and code in ('lifecycle.archived', 'lifecycle.unarchived'):
            by_cat['workflow'].add(code)
        elif ns in CATEGORY_LABELS:
            by_cat[ns].add(code)
        # 'foia.*', 'comms.*', 'compliance.*', 'system.*', 'lifecycle.created' etc.
        # are intentionally NOT in any category — they're staff-only or low-signal
        # and shouldn't dominate the per-record filter UI.
    _VERBS_BY_CATEGORY = by_cat
    return _VERBS_BY_CATEGORY


def _categories_for_verbs(verbs: list[str]) -> list[str]:
    """Reverse: given a list of verb codes, return the category keys whose
    verbs are FULLY covered.  Empty input list → return all categories
    (per the watcher contract: empty notify_verbs = all verbs)."""
    if not verbs:
        return list(CATEGORY_LABELS.keys())
    verb_set = set(verbs)
    covered = []
    for cat, cat_verbs in _verbs_by_category().items():
        if cat_verbs and cat_verbs.issubset(verb_set):
            covered.append(cat)
    return covered


def _verbs_for_categories(categories: list[str]) -> list[str]:
    """Forward: union of verb codes for the given category keys.  If the
    user selected ALL categories, return [] so notify_verbs stays empty
    (which means 'all visible verbs' on the matches() side)."""
    valid = [c for c in categories if c in CATEGORY_LABELS]
    if len(valid) == len(CATEGORY_LABELS):
        return []  # all selected → empty list = match all verbs
    by_cat = _verbs_by_category()
    out: set[str] = set()
    for cat in valid:
        out.update(by_cat.get(cat, set()))
    return sorted(out)


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


@require_POST
@login_required
def set_categories(request):
    """Set the user's per-record notify_verbs from a list of category keys.

    POST data:
        target_ct_id -- ContentType.pk for the target model (required)
        target_id    -- target's primary key (required)
        categories   -- comma-separated list of category keys
                        (e.g. 'workflow,diligence'). Categories not in
                        CATEGORY_LABELS are ignored.

    Behaviour:
        * If no Watcher row exists, returns 404 — must follow first.
        * If categories list contains all known categories: notify_verbs=[]
          (which the matches() contract treats as 'all verbs').
        * Otherwise: notify_verbs = sorted union of verb codes from selected
          categories.

    Returns JSON:
        {
            "categories": ["workflow", ...],   -- the active categories after save
            "notify_verbs": [...]              -- the resolved verb list (or [])
        }
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

    raw = (request.POST.get('categories') or '').strip()
    categories = [c.strip() for c in raw.split(',') if c.strip()] if raw else []

    watcher = Watcher.objects.filter(
        user=request.user, target_ct=ct, target_id=target_id,
    ).first()
    if watcher is None:
        return JsonResponse(
            {'error': 'Not following this record. Toggle follow first.'},
            status=404,
        )

    notify_verbs = _verbs_for_categories(categories)
    watcher.notify_verbs = notify_verbs
    watcher.save(update_fields=['notify_verbs'])

    return JsonResponse({
        'categories': _categories_for_verbs(notify_verbs),
        'notify_verbs': notify_verbs,
    })
