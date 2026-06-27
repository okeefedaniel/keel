"""Permission gate for /ops/.

Mirrors `keel_site.audit.permissions.can_view_audit` exactly: superuser OR
`system_admin` / `agency_admin` ProductAccess on any product. The aggregator
itself scopes per-product visibility downstream — this gate is just the
"may you see this page at all" check.

DEMO_MODE does NOT relax this gate. /ops/ is staff-shaped even on demo
instances (same rationale as /audit/ — leaking ops infra into demo would
defeat the purpose of having a sandboxed demo surface).
"""
from __future__ import annotations

_OPS_ROLES = ('system_admin', 'agency_admin')


def can_view_ops(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.product_access.filter(
        role__in=_OPS_ROLES, is_active=True,
    ).exists()


def visible_products_for(user) -> list[str]:
    """Product codes this user may see on /ops/.

    Superusers see every product in ``KEEL_FLEET_PRODUCTS``. Agency / system
    admins see only the products where they hold the role, intersected with
    the canonical fleet list. Same logic as audit visibility — kept distinct
    so /ops/ could diverge later without entangling /audit/'s rules.
    """
    from django.conf import settings

    fleet_codes = [p['code'] for p in getattr(settings, 'KEEL_FLEET_PRODUCTS', [])]
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser:
        return fleet_codes
    accessible = set(
        user.product_access.filter(
            role__in=_OPS_ROLES, is_active=True,
        ).values_list('product', flat=True)
    )
    return [code for code in fleet_codes if code in accessible]
