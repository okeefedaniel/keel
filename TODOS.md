# DockLabs suite — TODOS

Cross-product or suite-wide engineering work that's been identified but not yet scheduled. Product-specific TODOs live in each product's own repo.

## Reconcile cross-product template overrides

**What:** Three products ship copies of other products' base templates that still load v1 CSS (`docklabs.css`) instead of the shared v2:
- `beacon/templates/admiralty/base.html:22`
- `harbor/templates/manifest/base.html:16`
- `lookout/templates/account/base.html:12`

**Why:** These override bundles shadow peer products' templates when the containing product is deployed. They likely predate proper template extraction — the same pattern as the `signatures/` duplication flagged in `keel/CLAUDE.md` Known Deviations. After v3 ships, any request that hits one of these routes will render in v1 aesthetic while the rest of the suite renders in v3. Low user-visibility unless those specific routes are exercised, but unprincipled.

**Context:** Identified during the design-v3 migration plan's fork reconciliation step (April 2026). Investigation didn't happen inline because it's not blocking v3 — this can ship before OR after v3.

**Action items:**
1. Determine *why* each override exists (intentional divergence vs. stale copy-paste).
2. If stale: delete the override and rely on the peer product's canonical template (via `keel.core` or the peer's own app).
3. If intentional: fold the product-specific bits into a documented mixin or block override, not a full template copy.
4. Bump the `css/docklabs.css` references to `css/docklabs-v2.css` regardless.

**Depends on / blocked by:** Nothing. Can be done independently. Worth bundling with the pending `signatures/` extraction work since the root cause is similar.

**Effort:** ~1-2 hours CC-assisted across 3 repos.
