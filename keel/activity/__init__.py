"""keel.activity — suite-wide hierarchical activity layer.

Architecture: AuditLog (system) → Activity (product, user-visible) → Notification (per-user push).

Two tracks for creating Activity rows:

1. **Track A — auto-promotion via registry.** For simple "model X saved → activity row" cases.
   Promotion rules registered in `keel/activity/product_promotions.py` are looked up by
   ``(audit.entity_type, audit.action)``. Suitable for create/delete events where the audit
   row IS the activity event (e.g. ProjectCollaborator create → collab.added activity).

2. **Track B — explicit ``record_activity()`` calls.** For domain-rich verbs where the audit
   row's snapshot doesn't carry enough structured information (e.g. status transitions,
   signing events). The product service that performs the action calls ``record_activity()``
   directly with explicit metadata. Writes both AuditLog AND Activity in one transaction.

See ``MIGRATION-NOTES.md`` for the spike findings that drove this design.
"""

default_app_config = 'keel.activity.apps.ActivityConfig'

# Public API surface — bumped only when a downstream product depends on a new symbol.
__all__ = [
    'record_activity',
    'AbstractActivity',
    'AbstractWatcher',
    'PromotionRule',
    'PromotionRegistry',
    'activity_promotion',
]
