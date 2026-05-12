# DockLabs suite — TODOS

Cross-product or suite-wide engineering work that's been identified but not yet scheduled. Product-specific TODOs live in each product's own repo.

## Mount `/api/v1/audit-feed/` on all 9 sibling products

**What:** Keel's new `/audit/` page fans out across the suite via `keel.feed.audit_feed_view`, but each sibling product needs to mount its own audit-feed endpoint before its chip on Keel flips from gray "pending" to green "ok". The reference implementation is at `keel/feed/audit_feed_example.py` in keel ≥ 0.38.0 — each product copies the file, points the `AuditLog` import at its concrete model, wires `path('api/v1/audit-feed/', build_audit)`, and bumps `keel>=0.38.0` in `requirements.txt`.

**Why:** Until the endpoint ships per product, Keel's audit page shows that product as "pending" with no rows. The aggregator tolerates this (decision A9 — graceful partial-suite), so Keel itself can ship now and each product rolls out on its own cadence.

**Per-product checklist (9 PRs, one per product):**
1. Copy `keel/feed/audit_feed_example.py` → `<product>/api/audit_feed.py`
2. Replace the `from beacon.companies.models import AuditLog` line with the right concrete model for this product
3. Wire URL: `path('api/v1/audit-feed/', build_audit, name='audit-feed')` under your existing `/api/v1/` mount
4. Bump `requirements.txt`: `keel @ git+https://github.com/okeefedaniel/keel.git@v0.38.0`
5. Deploy. Smoke test with curl + `HELM_FEED_API_KEY`. Confirm Keel `/audit/` chip flips to green.

**Status by product:** admiralty ❌ · beacon ❌ · bounty ❌ · harbor ❌ · helm ❌ · lookout ❌ · manifest ❌ · purser ❌ · yeoman ❌

**Effort:** ~15 min per product, no novel design, no test suite expansion required.


## ~~Reconcile cross-product template overrides~~ — DONE 2026-04-21

Resolved during v3 polish. Each of the three overrides is actively rendered (beacon serves FOIA through a compat layer mapped in `beacon/foia/compat.py:106`; harbor's signatures app renders through `manifest/base.html` via `harbor/signatures/context_processors.py:19`; lookout's allauth picks up `account/base.html` by template lookup). All three were bumped from `docklabs.css` (v1) to `docklabs-v2.css` (v3).

Deeper action item (fold product-specific bits into documented mixins) intentionally not done — the templates work as full copies. The right time to refactor is when the underlying apps extract (see signatures extraction below).

## Extract duplicated `signatures/` app from Harbor + Manifest

**What:** Harbor and Manifest both ship their own `signatures/` Django app with byte-identical `services.py` and a ~12-line diff in `views.py`. The extraction plan is scaffolded at `keel/keel/signatures/__init__.py` but the move is blocked on a migration strategy — both products' `signatures` app label carries live migration history.

**Why:** Every change to signing behavior has to be made twice. The duplicated templates + context processors that loaded the wrong CSS until today are a symptom of the same root cause.

**Context:** Flagged in `keel/CLAUDE.md` Known Deviations since v2 era. Not blocked on v3.

**Action items:**
1. Propose a migration strategy that unifies both products' `signatures_*` tables under the shared `keel.signatures` app label without data loss.
2. Move the identical service code into `keel/keel/signatures/`.
3. Deprecate the per-product signatures apps in a coordinated release.

**Effort:** ~1-2 days of engineering work (migration planning is the hard part).
