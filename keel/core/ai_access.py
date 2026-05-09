"""AI feature gating — three-layer access control.

A user can use an AI feature in product P iff **all** of:

1. **Org subscription** — ``OrganizationProductSubscription(org=user.org,
   product=P, is_active=True, ai_enabled=True)`` exists.
2. **User access** — ``ProductAccess(user=user, product=P,
   is_active=True, ai_enabled=True)`` exists.
3. **Key present** — ``user.has_anthropic_key()`` returns True.

The first two layers control whether AI is *visible*. The third
controls whether it's *usable*: if 1+2 pass but 3 fails, the AI
surface still renders, but disabled with an inline "you have not yet
put in your API key" prompt linking to settings.

This module is the single source of truth for the predicate. Don't
re-implement the check in product code — call ``user_can_use_ai`` or
``user_ai_state``.

Standalone-mode notes
---------------------

When running on a product whose ``OrganizationProductSubscription``
table doesn't exist (the product was deployed without keel.accounts
migrations applied — uncommon but possible during partial-suite
adoption), the helpers return the standalone-mode answer: AI is
gated only by ``ProductAccess.ai_enabled`` and the user having a key.
This keeps standalone deployments functional.
"""

from __future__ import annotations

import functools
import logging
from typing import Literal

from django.conf import settings
from django.http import Http404, HttpResponseForbidden

logger = logging.getLogger(__name__)

# Type alias used by ``user_ai_state`` so callers can do exhaustive
# match/case dispatch without importing typing.Literal repeatedly.
AIState = Literal['off', 'needs_key', 'ready']


def _resolve_product_code(product_code: str | None) -> str:
    """Default to ``settings.KEEL_PRODUCT_CODE`` (or ``KEEL_PRODUCT_NAME`` lower-cased) when not given."""
    if product_code:
        return product_code
    return (
        getattr(settings, 'KEEL_PRODUCT_CODE', '')
        or getattr(settings, 'KEEL_PRODUCT_NAME', '').lower()
    )


def _org_has_ai(user, product_code: str) -> bool:
    """Layer 1: does the user's org subscribe to this product with AI on?

    Returns True for cross-org superusers (dokadmin) without further
    checks — they can use AI in every product. The DB-level CheckConstraint
    already enforces that non-superusers have an organization.

    Standalone vs schema-drift: when ``OrganizationProductSubscription``
    can't be queried, the behavior is gated on ``KEEL_STANDALONE_MODE``:

    - ``True`` (explicit standalone deployment) — bypass layer 1 and
      defer the gate decision to layer 2 (per-user ``ProductAccess``).
      This is the intentional standalone-mode contract.
    - ``False`` (default — suite mode or unknown) — fail closed. A
      query failure here means schema drift / partial migration / DB
      hiccup, not an intentional standalone deploy. Granting AI on
      exception would be a confused-deputy bug.
    """
    if getattr(user, 'is_superuser', False):
        return True
    org = getattr(user, 'organization', None)
    if org is None:
        return False
    try:
        from keel.accounts.models import OrganizationProductSubscription
        return product_code in OrganizationProductSubscription.ai_enabled_product_codes(org)
    except Exception:
        if getattr(settings, 'KEEL_STANDALONE_MODE', False):
            # Explicit standalone: no org-sub table, defer to layer 2.
            return True
        # Suite-mode or unknown: schema/DB issue, fail closed.
        logger.warning(
            'AI gate layer 1 failed for product=%s with KEEL_STANDALONE_MODE=False '
            '— failing closed. Set KEEL_STANDALONE_MODE=True for standalone deploys.',
            product_code,
        )
        return False


def _user_has_ai(user, product_code: str) -> bool:
    """Layer 2: does the user's per-product ``ProductAccess`` have AI on?

    Superusers also pass — same rationale as layer 1.
    """
    if getattr(user, 'is_superuser', False):
        return True
    try:
        return user.product_access.filter(
            product=product_code, is_active=True, ai_enabled=True,
        ).exists()
    except Exception:  # noqa: BLE001 — defensive against schema drift
        return False


def _oidc_ai_key_present(user) -> bool:
    """Read ai_key_present from stored OIDC claims (SocialAccount.extra_data).

    Used as a fallback in suite-mode products where the user's Anthropic key
    lives in Keel's database, not the local product's database. The claim is
    stamped at login time by Keel's OIDC validator (requires the 'ai' scope).
    """
    try:
        from allauth.socialaccount.models import SocialAccount
        acct = SocialAccount.objects.filter(user=user, provider='keel').first()
        if acct is None:
            return False
        data = acct.extra_data or {}
        # allauth 65+ stores claims under 'userinfo' / 'id_token' keys.
        userinfo = data.get('userinfo')
        if isinstance(userinfo, dict) and 'ai_key_present' in userinfo:
            return bool(userinfo['ai_key_present'])
        id_token = data.get('id_token')
        if isinstance(id_token, dict) and 'ai_key_present' in id_token:
            return bool(id_token['ai_key_present'])
        return bool(data.get('ai_key_present', False))
    except Exception:  # noqa: BLE001 — defensive; allauth may not be installed
        return False


def _user_has_key(user) -> bool:
    """Layer 3: has the user set an Anthropic key?

    Checks the local encrypted field first (fast, no network). Falls back to
    the OIDC ai_key_present claim for suite-mode products where the key lives
    in Keel's database and the local field is always empty.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    method = getattr(user, 'has_anthropic_key', None)
    if callable(method) and method():
        return True
    return _oidc_ai_key_present(user)


def user_can_use_ai(user, product_code: str | None = None) -> bool:
    """All three layers pass — the user can actually use AI right now."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    code = _resolve_product_code(product_code)
    if not code:
        return False
    return (
        _org_has_ai(user, code)
        and _user_has_ai(user, code)
        and _user_has_key(user)
    )


def user_ai_state(user, product_code: str | None = None) -> AIState:
    """Return one of {'off', 'needs_key', 'ready'} for template rendering.

    - ``'off'`` — at least one of the visibility gates is False; the AI
      surface should be hidden entirely.
    - ``'needs_key'`` — visibility gates pass but the user has no key
      configured; render the surface with an inline prompt.
    - ``'ready'`` — go.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return 'off'
    code = _resolve_product_code(product_code)
    if not code:
        return 'off'
    if not _org_has_ai(user, code) or not _user_has_ai(user, code):
        return 'off'
    if not _user_has_key(user):
        return 'needs_key'
    return 'ready'


def ai_enabled_products_for_user(user) -> list[str]:
    """Return product codes where the user has AI access (layers 1+2).

    Used by the OIDC validator to build the ``ai_enabled_products``
    claim, by the AI settings panel banner ("AI is enabled on these
    products"), and by any cross-product UI that wants to surface
    "you have AI on N products" without iterating all known codes.

    Layer 3 (key presence) is intentionally NOT included — knowing
    which products are AI-eligible is independent of whether the user
    has set a key yet. ``ai_key_present`` is its own claim.

    Per-request caching: the result is memoized on the user instance
    via ``user._cached_ai_products``. The context_processor calls this
    on every authenticated request, so without the cache every page
    render pays 2 queries (one ``OrganizationProductSubscription``
    filter + one ``ProductAccess`` filter). The Django ``HttpRequest``
    user instance lives only for the request, so the cache TTL is
    effectively the request lifetime.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    cached = getattr(user, '_cached_ai_products', None)
    if cached is not None:
        return cached

    result = _compute_ai_enabled_products_for_user(user)
    try:
        user._cached_ai_products = result
    except Exception:
        # AnonymousUser or some other read-only proxy — skip cache.
        pass
    return result


def _compute_ai_enabled_products_for_user(user) -> list[str]:
    """Inner: do the actual queries. Use ``ai_enabled_products_for_user``."""
    try:
        from keel.accounts.models import (
            OrganizationProductSubscription, ProductAccess,
        )
    except Exception:  # noqa: BLE001 — defensive
        return []
    org = getattr(user, 'organization', None)
    if getattr(user, 'is_superuser', False):
        # Superuser shortcut: every product the user has ProductAccess
        # for, regardless of org-sub state. The org-sub gate doesn't
        # apply to dokadmin, but the per-user flag still does so an
        # admin can opt themselves out of AI on a given product.
        per_user = set(
            ProductAccess.objects.filter(
                user=user, is_active=True, ai_enabled=True,
            ).values_list('product', flat=True)
        )
        return sorted(per_user)
    if org is None:
        return []
    try:
        org_codes = set(OrganizationProductSubscription.ai_enabled_product_codes(org))
    except Exception:  # noqa: BLE001
        org_codes = set()
    user_codes = set(
        ProductAccess.objects.filter(
            user=user, is_active=True, ai_enabled=True,
        ).values_list('product', flat=True)
    )
    return sorted(org_codes & user_codes)


# ---------------------------------------------------------------------------
# View decorator
# ---------------------------------------------------------------------------
def require_ai_access(product_code: str | None = None, *, on_failure: str = 'forbidden'):
    """Wrap a view so it requires the user to pass layers 1+2.

    Layer 3 (key presence) is intentionally NOT required by this
    decorator — views that produce HTML should render the "needs key"
    prompt rather than 403. Use this on AI-only API endpoints (e.g.
    JSON streaming chat) where the request can't gracefully degrade
    without a key.

    Args:
        product_code: explicit product code; defaults to settings.
        on_failure: 'forbidden' (default) returns 403; 'http404' raises Http404.
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = getattr(request, 'user', None)
            code = _resolve_product_code(product_code)
            if (
                user is None
                or not getattr(user, 'is_authenticated', False)
                or not _org_has_ai(user, code)
                or not _user_has_ai(user, code)
            ):
                if on_failure == 'http404':
                    raise Http404('AI feature not available.')
                return HttpResponseForbidden('AI feature not available.')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
