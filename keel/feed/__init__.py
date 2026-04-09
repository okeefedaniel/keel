"""keel.feed — shared Helm feed framework.

Products expose /api/v1/helm-feed/ using the ``helm_feed_view`` decorator
or ``HelmFeedMixin``. Helm pulls data via ``fetch_feeds`` management command.
"""
