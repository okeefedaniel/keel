"""JSON autocomplete endpoint for the @-mention picker.

Returns a two-array JSON shape so the JS picker can render users and
contacts with distinct visual treatment:

    {
        "users":    [{username, display_name, avatar_url, has_product_access}],
        "contacts": [{slug, display_name, organization, source_product, url}]
    }

Org-scoped, throttled, audit-logged. Single-letter queries return empty
arrays (raises the cost of user-enumeration scraping).
"""
from __future__ import annotations

import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .beacon import is_available as beacon_available
from .beacon import search_contacts as beacon_search_contacts

logger = logging.getLogger(__name__)

_MIN_QUERY_LEN = 2
_MAX_RESULTS_PER_KIND = 25


def _current_product_code() -> str:
    return (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower()


def _audit_search(user, q: str) -> None:
    """Log each mention-search query for audit. Silent if no AuditLog wired."""
    model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', None)
    if not model_path:
        return
    try:
        Model = apps.get_model(model_path)
        Model.objects.create(
            user=user,
            action='mention_search',
            metadata={'q': q[:128], 'product': _current_product_code()},
        )
    except Exception:
        logger.debug('mention_search audit log write failed', exc_info=True)


def _build_user_avatar_url(user) -> str:
    """Best-effort avatar URL extraction. Returns '' when unavailable."""
    url = getattr(user, 'avatar_url', '') or ''
    if url:
        return url
    avatar = getattr(user, 'avatar', None)
    if avatar and getattr(avatar, 'url', ''):
        try:
            return avatar.url
        except Exception:
            return ''
    return ''


def _user_search(q: str, requester) -> list[dict]:
    User = get_user_model()
    qs = User.objects.filter(is_active=True)

    requester_org = getattr(requester, 'organization', None)
    is_superuser = bool(getattr(requester, 'is_superuser', False))

    if is_superuser and requester_org is None:
        pass
    elif requester_org is None:
        logger.warning(
            'mentions_search: non-superuser %r has organization=None',
            getattr(requester, 'username', '?'),
        )
        return []
    else:
        qs = qs.filter(organization=requester_org)

    # Username-prefix OR display-name substring.
    from django.db.models import Q
    qs = qs.filter(
        Q(username__istartswith=q)
        | Q(first_name__icontains=q)
        | Q(last_name__icontains=q)
    )

    product = _current_product_code()
    if product:
        qs = qs.filter(
            product_access__product=product,
            product_access__is_active=True,
        )

    qs = qs.exclude(pk=requester.pk).distinct()[:_MAX_RESULTS_PER_KIND]

    out = []
    for u in qs:
        display = u.get_full_name() or u.username
        out.append({
            'username': u.username,
            'display_name': display,
            'avatar_url': _build_user_avatar_url(u),
            'has_product_access': True,  # already filtered above
        })
    return out


@require_GET
@login_required
def mentions_search(request):
    """Picker autocomplete. ``?q=<query>`` returns users + contacts."""
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'authentication required'}, status=401)

    q = (request.GET.get('q', '') or '').strip()
    if len(q) < _MIN_QUERY_LEN:
        return JsonResponse({'users': [], 'contacts': []})

    _audit_search(request.user, q)

    users = _user_search(q, request.user)

    contacts: list[dict] = []
    if beacon_available():
        try:
            raw = beacon_search_contacts(q, requester=request.user)
        except Exception:
            logger.info('mentions_search: contact lookup failed', exc_info=True)
            raw = []
        # Normalize to documented shape; tolerate Beacon returning extra keys.
        for item in raw[:_MAX_RESULTS_PER_KIND]:
            if not isinstance(item, dict) or not item.get('slug'):
                continue
            contacts.append({
                'slug': item.get('slug', ''),
                'display_name': item.get('display_name', ''),
                'organization': item.get('organization', ''),
                'source_product': 'beacon',
                'url': item.get('url', ''),
            })

    return JsonResponse({'users': users, 'contacts': contacts})
