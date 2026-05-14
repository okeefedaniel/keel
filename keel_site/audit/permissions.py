"""Permission helpers for /audit/.

Per the suite ACL contract in keel/CLAUDE.md, only superuser /
system_admin / agency_admin roles see cross-product audit data, and
the agency_admin scope is per-product (not suite-wide).
"""
from __future__ import annotations

from django.conf import settings

_AUDIT_ROLES = ('system_admin', 'agency_admin')


def can_view_audit(user) -> bool:
    """Gate for /audit/.

    Returns True for superusers and for any user with an active
    ``system_admin`` or ``agency_admin`` ProductAccess on any product.

    DEMO_MODE does NOT relax this gate (review decision A2); even on a
    demo instance the page is staff-shaped.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.product_access.filter(
        role__in=_AUDIT_ROLES, is_active=True,
    ).exists()


def visible_products_for(user) -> list[str]:
    """Product codes this user may see in /audit/.

    Superusers see every product in ``KEEL_FLEET_PRODUCTS`` plus 'keel'
    for the Keel-local audit log. Agency / system admins see only the
    products where they hold the role, intersected with the canonical
    fleet list (so a stale ProductAccess for a decommissioned product
    does not leak visibility).

    Non-superusers do NOT get blanket 'keel' visibility — that would let
    an agency_admin of Bounty read every Keel user's SSO failure +
    email. Their own Keel events are still reachable via the standard
    'view my access history' path; cross-product audit is the wrong
    surface for that.
    """
    fleet_codes = [p['code'] for p in getattr(settings, 'KEEL_FLEET_PRODUCTS', [])]
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser:
        return ['keel', *fleet_codes]
    granted = set(
        user.product_access.filter(
            role__in=_AUDIT_ROLES, is_active=True,
        ).values_list('product', flat=True).distinct()
    )
    # Intersect with the canonical fleet to drop stale grants.
    return [c for c in fleet_codes if c in granted]
