"""Keel /ops/ console — cross-product operational visibility.

Three rows:
1. Scheduling (Keel-local in v1; cross-product roll-up deferred to a sibling
   `/api/v1/scheduling-feed/` endpoint not yet built).
2. Activity system-events lane — cross-product fan-out via
   `keel.feed.client.fetch_product_activity`. The primary payload — what
   "/ops/ at a glance" was designed to surface.
3. Canary (Keel-local in v1; per-product canary fan-out requires distributing
   `KEEL_METRICS_TOKEN` across products and is deferred).

Permissions mirror /audit/: superuser OR `system_admin`/`agency_admin`
ProductAccess on any product. DEMO_MODE does not relax the gate.
"""
