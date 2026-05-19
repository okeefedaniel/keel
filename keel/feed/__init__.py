"""keel.feed — shared Helm feed framework.

Products expose /api/v1/helm-feed/ using the ``helm_feed_view`` decorator
or ``HelmFeedMixin``. Helm pulls data via ``fetch_feeds`` management command.

Products expose /api/v1/audit-feed/ using the ``audit_feed_view`` decorator.
Keel's /audit/ page fans out across the suite via ``fetch_product_audit``.
"""
from keel.feed.client import (
    fetch_product_activity,
    fetch_product_audit,
    fetch_product_feed,
)
from keel.feed.views import (
    activity_feed_view,
    audit_feed_view,
    helm_activity_view,
    helm_feed_view,
    helm_inbox_view,
)

__all__ = [
    'activity_feed_view',
    'audit_feed_view',
    'fetch_product_activity',
    'fetch_product_audit',
    'fetch_product_feed',
    'helm_activity_view',
    'helm_feed_view',
    'helm_inbox_view',
]
