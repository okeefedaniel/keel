# DockLabs suite — TODOS

Cross-product or suite-wide engineering work that's been identified but not yet scheduled. Product-specific TODOs live in each product's own repo.

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
