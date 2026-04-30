"""Suite-wide operational metrics — the canary endpoint.

Returns a small JSON payload of counters + boolean health flags, designed
to be polled by an external monitor (GitHub Actions, BetterUptime, etc.)
on a 15-minute cadence. The four core flags (``audit_silent_24h``,
``cron_silent_24h``, ``cron_failures_24h``, ``notifications_failing``)
all read from keel-shipped tables, so every product gets the same
canary by mounting one URL.

Products may add product-specific gauges via ``extras_callable``:

    # product/api/metrics.py
    from keel.ops.canary import build_canary_payload, _safe_count
    from keel.ops.views import canary_view

    def _product_extras(now, last_24h, last_1h, **kwargs):
        return {
            'projects_active': _safe_count('helm_tasks.Project', status='active'),
            ...
        }

    metrics = canary_view(extras_callable=_product_extras)

Or use the bundled URL include (no extras):

    # product/urls.py
    path('api/v1/metrics/', include('keel.ops.urls')),

Auth: staff session OR ``Authorization: Bearer $KEEL_METRICS_TOKEN``.
Without the token bypass, no external monitoring can reach the canary.
"""
default_app_config = 'keel.ops.apps.OpsConfig'

from keel.ops.canary import build_canary_payload  # noqa: E402,F401
