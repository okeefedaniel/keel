# DockLabs suite — TODOS

Cross-product or suite-wide engineering work that's been identified but not yet scheduled. Product-specific TODOs live in each product's own repo.

## Mount `/api/v1/audit-feed/` on Beacon

**What:** Keel's `/audit/` page (shipped 2026-05-14 in keel `v0.40.1`) fans out across the suite via `keel.feed.audit_feed_view`. 8 of 9 sibling products are already mounted; only **Beacon** remains pending because its `design/beacon-header-and-dashboard` feature branch was in flight when the suite-wide rollout happened. Once that branch lands, apply the same recipe.

**Recipe:**
1. Copy `keel/feed/audit_feed_example.py` → `beacon/api/audit_feed.py` (or `beacon/companies/audit_feed.py` if you'd rather keep it next to `companies/helm_feed.py`)
2. Set the import to the concrete model: `from beacon.companies.models import AuditLog`
3. Rename `build_audit` → `beacon_audit_feed` for consistency with the other products
4. Wire URL in `beacon/api/urls.py`: `path('audit-feed/', beacon_audit_feed, name='audit-feed')` under the existing `/api/v1/` include
5. Bump `requirements.txt`: `keel @ git+https://github.com/okeefedaniel/keel.git@v0.41.0` (or whatever's current)
6. Open PR → merge → Railway auto-deploys (or `railway up --service beacon --detach` if the "Wait for CI" gate wedges it in QUEUED — see CLAUDE.md Known Deviations)
7. Smoke test: `curl -H "Authorization: Bearer $HELM_FEED_API_KEY" "https://beacon.docklabs.ai/api/v1/audit-feed/?window_start=...&window_end=...&limit=1"` should return 200
8. Reload `https://keel.docklabs.ai/audit/` as `dokadmin` — Beacon chip should flip from gray hourglass to green check

**Status by product:** admiralty ✅ · **beacon ⏳** · bounty ✅ · harbor ✅ · helm ✅ · lookout ✅ · manifest ✅ · purser ✅ · yeoman ✅

**Effort:** ~15 min, no novel design, no test suite expansion required.


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
