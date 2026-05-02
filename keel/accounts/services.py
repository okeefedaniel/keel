"""Org-aware service layer for keel.accounts.

Pulled into a module separate from models.py so the reconcile
function isn't subject to ``models.py``'s import-time circular
constraints (the ``KeelUser.save`` hook imports it lazily).
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def reconcile_user_product_access(user, force_logout: bool = True) -> int:
    """Deactivate ProductAccess rows the user's org no longer subscribes to.

    Called from ``KeelUser.save`` whenever ``organization`` changes
    (the snapshot pattern in ``KeelUser.__init__`` detects the change),
    and from the ``reconcile_org_product_access`` management command
    on a daily cron.

    Closes CSO finding S1 (privilege bleed on org reassignment): a user
    moved from an org with the full suite to an org with only Bounty
    keeps their existing ProductAccess rows otherwise; this function
    sweeps them.

    Closes CSO finding S2 (stale JWT) when ``force_logout=True``:
    bumping ``user.last_logout_at`` invalidates any active per-product
    sessions on the next request via ``SessionFreshnessMiddleware``.

    Returns the count of ProductAccess rows deactivated. Returns 0
    immediately for cross-org superusers (no org → no constraint to
    enforce).
    """
    if user.is_superuser or user.organization_id is None:
        return 0

    # Imported here to avoid the import-time circular: services.py is
    # imported from models.py via KeelUser.save's lazy local import.
    from keel.accounts.models import (
        OrganizationProductSubscription,
        ProductAccess,
    )

    subscribed = OrganizationProductSubscription.active_product_codes(
        user.organization
    )

    with transaction.atomic():
        deactivated_qs = (
            ProductAccess.objects
            .filter(user=user, is_active=True)
            .exclude(product__in=subscribed)
        )
        # Snapshot for logging BEFORE the update, so we can write a
        # readable line if something cares to audit which products
        # got revoked.
        revoked_products = list(
            deactivated_qs.values_list('product', flat=True)
        )
        deactivated = deactivated_qs.update(is_active=False)

        if deactivated and force_logout:
            # Reuse the existing last_logout_at infrastructure
            # (deployed across all 9 products in keel >= 0.20.0)
            # rather than introducing a new column. SessionFreshness
            # middleware will see the bumped timestamp and tear down
            # stale per-product sessions on the next request.
            user.last_logout_at = timezone.now()
            # update_fields prevents triggering KeelUser.save's own
            # org-change detection (organization didn't change here).
            user.__class__.objects.filter(pk=user.pk).update(
                last_logout_at=user.last_logout_at,
            )

    if deactivated:
        logger.info(
            'reconcile_user_product_access: revoked %d ProductAccess '
            'rows for user=%s org=%s; revoked_products=%s force_logout=%s',
            deactivated,
            user.pk,
            user.organization_id,
            revoked_products,
            force_logout,
        )

    return deactivated


def reconcile_all_users(*, force_logout: bool = False) -> dict:
    """Sweep every user, reconciling their ProductAccess.

    Called by the ``reconcile_org_product_access`` management command
    (daily cron) so admin actions that bypass ``KeelUser.save`` (raw
    SQL fixes, replication-based bulk imports) still get caught.

    ``force_logout=False`` by default for the cron path so a sweep
    doesn't kick every user out of their session every night. Direct
    org-change reconciliation (via the save hook) does pass
    ``force_logout=True``.

    Returns a small report dict for logging.
    """
    from keel.accounts.models import KeelUser

    total_users = 0
    total_revoked = 0

    qs = KeelUser.objects.filter(
        is_active=True,
        is_superuser=False,
        organization__isnull=False,
    ).select_related('organization')

    for user in qs.iterator():
        total_users += 1
        revoked = reconcile_user_product_access(user, force_logout=force_logout)
        total_revoked += revoked

    logger.info(
        'reconcile_all_users: scanned %d users, revoked %d ProductAccess rows',
        total_users, total_revoked,
    )
    return {
        'users_scanned': total_users,
        'rows_revoked': total_revoked,
    }
