# DockLabs Suite Review — Actions / Notifications / Audit Subsystem

**Date:** 2026-06-27
**Reviewer:** Claude (gstack-style review, code-grounded)
**Scope:** keel (v0.55.0) + 9 product repos at /Users/dok/Code/CT/
**Method:** Architecture read of keel modules + suite-wide grep across 9 products on 8 dimensions

> A backup copy of this review lives at `/Users/dok/Code/CT/keel/docs/plans/audit-notifications-review-2026-06-27.md` — `~/.claude/plans/` was cleaned by a housekeeping pass at 17:25Z today, so the canonical path is not safe long-term.

---

## Executive Summary

**Architecture is sound, adoption is uneven, the `/ops/` story is unrealized.**

The subsystem keel ships is in good shape: AuditLog is schema-enforced for user actions only (`user NOT NULL` + `CheckConstraint`); Activity is the canonical "what happened" stream with Track A (auto-promotion) and Track B (`record_activity` / `record_system_event`); notifications fan out from Activity via `dispatch_activity_notifications`; the declarative `@scheduled_job(emits='verb.name')` decorator on the scheduler eliminates the lazy-summary risk. The 9 products all have concrete `AuditLog` + `Activity` subclasses and all mount `/api/v1/audit-feed/`.

But three structural gaps stand out: (1) **zero products mount `/api/v1/activity-feed/`** — the v0.47.1 cross-product aggregator has no consumers; (2) **only Bounty uses declarative `emits=`** (7 sites) and `record_system_event` (2 calls), so 8/9 products still have invisible crons; (3) **`/ops/` console doesn't exist** as a keel-level view, and even if Helm built one tomorrow it would have nothing to read. The plan's narrative ambition ("Dan opens /ops/ every morning to see what the suite is doing") is structurally blocked until those three gaps close.

The top three concrete actions: surface the `/api/v1/activity-feed/` mount gap and ship it as a single keel PR with a `check_activity_feed_wiring` boot check; convert each product's primary cron to `@scheduled_job(emits='verb.name')` (mechanical, ~15 min/product); build a thin first `/ops/` console in keel that consumes the activity aggregator. Everything else in this review is polish on top of those three.

---

## Architecture Map (current keel reality)

### 1. keel.core.audit subsystem

| Surface | File | Shape |
|---|---|---|
| `register_audited_model(label, name, skip_fields=)` | `keel/core/audit_signals.py:95` | No new kwargs since v0.46.3 — signature stable. Registers a model for post_save/post_delete auto-audit. |
| `_on_save` / `_on_delete` user gate | `keel/core/audit_signals.py:140,168` | Hard early-return on `user is None`. No bypass kwarg. System mutations route to Activity instead. |
| `log_audit(user, action, ...)` | `keel/core/audit.py:32` | Direct write API for explicit audit rows. Exception-swallowing — never breaks the originating action. |
| `AuditMiddleware` | `keel/core/middleware.py` | Sets `request.audit_ip` + thread-local `(user, ip)`. Try/finally clears on response or exception. Connects `user_logged_in` to write the login audit row. |
| `audit_context(user, ip='')` | `keel/core/middleware.py` (v0.47.0+) | Context manager to re-establish thread-local outside a request (Celery, shell, RunPython). Nesting-safe. |
| `AbstractAuditLog` | `keel/core/models.py:49-150+` | `user` is `NOT NULL` with `on_delete=PROTECT`. `CheckConstraint(Q(user_id__isnull=False))` for DB-level defense. `LOGIN_FAILED` + `SECURITY_EVENT` action choices removed at v0.46.0 (those events now go through Activity instead). |

### 2. keel.activity subsystem

| Surface | File | Shape |
|---|---|---|
| `AbstractActivity` | `keel/activity/models.py` | actor (FK, nullable for system events), verb, target GFK, action GFK, visibility (collaborators/agency/staff/public/stub), source_product, deep_link, source_label, audit_ref (FK to KEEL_AUDIT_LOG_MODEL, nullable, PROTECT), metadata, created_at. UniqueConstraint on audit_ref where not null (prevents Track A double-create). |
| `AbstractWatcher` | `keel/activity/models.py` | user + target GFK + filter_predicate (JSON, dotted paths) + notify_verbs (list). |
| `record_activity(actor, verb, target, ...)` | `keel/activity/services.py:80` | Track B for user-initiated events. Writes BOTH AuditLog AND Activity atomically. `skip_promotion_guard()` ContextVar prevents Track A from double-firing. When `actor=None`, skips the AuditLog write (NOT NULL constraint) and just writes Activity with `audit_ref=None`. |
| `record_system_event(verb, summary, ...)` | `keel/activity/services.py` (v0.47.0+) | Track B for system events. Writes ONLY Activity (never AuditLog). Validates `status ∈ ('ok','warn','failed','errored')`. Returns None when KEEL_ACTIVITY_MODEL is unset (fail-soft). |
| `dispatch_activity_notifications(activity)` | `keel/activity/dispatch.py:31` | post_save signal handler on Activity. Resolves recipients (custom resolver from NotificationType, else standard = collaborators + watchers + roles). Filters every recipient through `Activity.is_visible_to_user()` before firing notify(). |
| `PromotionRule` registry | `keel/activity/registry.py` | Track A — declarative rules mapping (entity_type, action) audit tuples to activity verbs with optional target/visibility/metadata resolvers. |
| `verbs.py` | `keel/activity/verbs.py` | Verb catalog: `collab.added`, `signing.signed`, `interaction.logged`, etc. Dotted snake_case keys mapped to human labels. |

### 3. keel.notifications dispatch

| Surface | File | Shape |
|---|---|---|
| `notify(event, actor=, recipients=, ...)` | `keel/notifications/dispatch.py:22` | Primary dispatch. Looks up NotificationType → resolves recipients → filters by per-user preferences → fans out per channel. Returns `{sent, skipped, errors, details}`. |
| `NotificationType` registry | `keel/notifications/registry.py` | Dataclass: key, label, category, default_channels, default_roles, priority, recipient_resolver, link_template, email templates. |
| Channels | `keel/notifications/channels/{in_app,email,sms,boswell}.py` | In-app writes Notification rows; email via Resend; SMS via Twilio; Boswell cross-product. |

### 4. keel.scheduling.decorators

| Surface | File | Shape |
|---|---|---|
| `@scheduled_job(slug, name, cron, owner, ..., emits=None)` | `keel/scheduling/decorators.py` | Wraps `BaseCommand` subclass: registers in `keel.scheduling.registry`, wraps `handle()` to write `CommandRun` rows. **emits=** (v0.48.0): when set, consumes the handler's return dict `{summary, status, counts, metadata}` and emits one Activity row. v0.48.1 tolerates None / non-dict returns (warn + skip). **Failure path is asymmetric**: success auto-emits if `emits=` set; exception path does NOT auto-emit a `status='failed'` Activity — caller must do it explicitly. |

### 5. keel.feed cross-product aggregators

| Surface | File | Shape |
|---|---|---|
| `audit_feed_view(build_audit_func)` | `keel/feed/views.py` | Per-product decorator for `/api/v1/audit-feed/`. Bearer auth (`HELM_FEED_API_KEY`), rate-limit, per-query-param cache. |
| `activity_feed_view(build_activity_func)` | `keel/feed/views.py` (v0.47.1+) | Sibling decorator for `/api/v1/activity-feed/`. Mirror of audit_feed_view, distinct cache namespace. Query params: window_start, window_end, q, verbs, status, limit. |
| `fetch_product_audit()` / `fetch_product_activity()` | `keel/feed/client.py` | Aggregator clients. Same status enum: ok / pending / unauthorized / timeout / error. |
| Reference examples | `keel/feed/audit_feed_example.py` + `keel/feed/activity_feed_example.py` | 25-line per-product wrappers products copy-and-adapt. |
| Aggregator UI | (Helm-local, NOT in keel) | The `/audit/` aggregator UI is at `keel.docklabs.ai/audit/` reading via fetch_product_audit. **No `/ops/` console exists yet** — neither in keel nor in Helm. |

### 6. keel.ops canary

| Surface | File | Shape |
|---|---|---|
| `build_canary_payload(extras_callable=)` | `keel/ops/canary.py` | `{flags: {audit_silent_24h, cron_silent_24h, cron_failures_24h, notifications_failing, audit_constraint_present}, healthy, counters, extras}`. |
| `canary_view(extras_callable=)` | `keel/ops/views.py` | Bearer or session-auth endpoint at `/api/v1/metrics/`. External pollers hit it every 15 min. |
| `user_can_view_canary(user)` | `keel/ops/canary.py` | Superuser OR product-scoped `system_admin` ProductAccess. NOT `is_staff` (would leak ops infra to demo users). |

---

## Product Coverage Matrix

| Product | AuditLog | Activity | register_audited_model (model count) | `@scheduled_job(emits=)` | `/api/v1/audit-feed/` | `/api/v1/activity-feed/` | `record_system_event` | `record_activity` |
|---|---|---|---|---|---|---|---|---|
| **admiralty** | ✅ `core/models.py` | ✅ `foia/activity_models.py` | 8 models | **0** | ✅ | ❌ | **0** | 6 |
| **beacon** | ✅ `core/models.py` | ✅ split across `pipeline/models.py` + `interactions/activity_models.py` ⚠️ | 18 models | **0** | ✅ | ❌ | **0** | 7 |
| **bounty** | ✅ `core/models.py` | ✅ `opportunities/activity_models.py` | 10 models | **7** ✅ | ✅ | ❌ | **2** | 8 |
| **harbor** | ✅ `core/models.py` | ✅ `applications/activity_models.py` | 28 models | **0** | ✅ | ❌ | **0** | 8 |
| **helm** | ✅ `core/models.py` | ✅ split across `tasks/activity_models.py` + `dashboard/activity.py` ⚠️ | 3 models | **0** | ✅ | ❌ | **0** | 13 |
| **lookout** | ✅ `core/models.py` | ✅ `tracking/activity_models.py` | 25 models | **0** | ✅ | ❌ | **0** | 7 |
| **manifest** | ✅ `signatures/models.py` | ✅ `signatures/activity_models.py` | 9 models | **0** | ✅ | ❌ | **0** | 2 |
| **purser** | ✅ `core/models.py` | ✅ `purser/activity_models.py` | 6 models | **0** | ✅ | ❌ | **0** | 5 |
| **yeoman** | ✅ `core/models.py` | ✅ `yeoman/activity_models.py` | 7 models | **0** | ✅ | ❌ | **0** | 4 |
| **TOTAL** | 9/9 | 9/9 (2 split) | 114 models | **7 calls (1 product)** | 9/9 | **0/9** | **2 calls (1 product)** | 60 calls across all |

**Reading this table:**
- **AuditLog + Activity contract:** universally adopted (excellent — Approach D landed everywhere).
- **`register_audited_model` is the dominant pattern:** 114 model registrations across the suite. Harbor leads with 28, Lookout with 25, Beacon with 18. The user gate from v0.46.3 means these are all FINE — they audit user mutations and silently skip cron mutations.
- **Track B `record_activity` is widely used:** every product has it (range 2-13 calls). Helm 13, harbor + bounty 8 each. This is the user-event narrative working as intended.
- **System-event surface is concentrated in Bounty alone:** 7 declarative emits + 2 explicit `record_system_event`. The other 8 products have zero system-event capture — their crons are invisible to /ops/ and to notifications.
- **`/api/v1/activity-feed/` is a 0/9 gap:** the cross-product aggregator is built in keel but nobody mounts it. /ops/ has no data to consume.

---

## Findings

Ordered by impact. Each finding includes a concrete file path, a fix recommendation, and effort estimate.

### F1 — 🔴 BLOCKER: Zero products mount `/api/v1/activity-feed/`

**Where:** all 9 products
**Evidence:** matrix row "/api/v1/activity-feed/" column = 0/9. Spot-check: `grep "api/v1/activity-feed" /Users/dok/Code/CT/*/urls.py` returns nothing.

**Why this matters:** the v0.47.1 cross-product Activity aggregator was the structural prerequisite for `/ops/`. Without per-product mounts, the aggregator client (`fetch_product_activity` in `keel/feed/client.py`) has nothing to fetch. Even if `/ops/` ships tomorrow, Row 2 (system-events lane) is empty across the suite except for any product reading its OWN local Activity table directly.

**Fix:** one keel PR adds a `check_activity_feed_wiring` boot check + one per-product PR per repo (~10 min each, mechanical copy of `audit_feed_example.py` pattern). Reference: `keel/feed/activity_feed_example.py` already exists and shows the exact 25-line shape. Mount at `path('api/v1/activity-feed/', activity_feed_view(build_activity), name='activity-feed')`.

**Effort:** 1 keel PR (boot check, ~30 min) + 9 product PRs (10 min each, fully parallelizable via subagents). **Total ~2-3 hours.**

---

### F2 — 🔴 BLOCKER: `/ops/` console doesn't exist anywhere

**Where:** no keel view, no Helm view
**Evidence:** `grep -r "/ops/" keel/keel_site/urls.py helm/helm_site/urls.py` returns no matches. The plan called for a 3-row `/ops/` console (scheduling chips / activity system-events / canary chips) at `keel.docklabs.ai/ops/`.

**Why this matters:** this is the visible payoff for the entire Approach D effort. Without `/ops/`, Dan has no single pane for "what is the suite doing" — he polls 9 dashboards. The aggregator + canary + scheduling-registry pieces are all in place; the console UI is what's missing.

**Fix:** ~2-day build in keel: new `OpsConsoleView` reading three rows from existing endpoints (cross-product scheduling.CommandRun roll-up, fetch_product_activity for system-events lane, build_canary_payload per-product roll-up). Gated on superuser-OR-any-system_admin. Reuse `/audit/` template patterns.

**Dependency:** F1 must ship first (Row 2 is empty without product mounts).

**Effort:** ~2 days human / ~3 hours CC for keel implementation. Real value: Dan opens it daily.

---

### F3 — 🟡 HIGH: 8 of 9 products have invisible crons (no `emits=` adoption)

**Where:** admiralty, beacon, harbor, helm, lookout, manifest, purser, yeoman — all have zero `@scheduled_job(emits=...)` call sites despite having scheduled jobs (verified via `grep "@scheduled_job" <product>/`).

**Evidence:** matrix `emits=` column shows 0 calls outside bounty. Spot-check: lookout's `sync_openstates_bills` (hourly), beacon's salesforce sync, admiralty's FOIA cache refresh — all silently run, write nothing to Activity, contribute nothing to /ops/.

**Why this matters:** without `emits=`, a cron's success is invisible (only the `CommandRun` row in scheduling dashboard, no narrative on /ops/) and its failure is invisible (no Activity row → no notification fan-out via `dispatch_activity_notifications`). Bounty's adoption of the pattern (commit-aligned with the original audit-rethink fire) is the reference; replicating it across the 8 other products is mechanical.

**Fix:** per-product PR adds `emits='verb.name'` kwarg to existing `@scheduled_job` decorators + refactors `handle()` to return the structured `{summary, counts, status, metadata}` dict. Bounty's `sync_federal_grants.py` is the working reference.

**Effort:** ~15 min per product × 8 products = ~2 hours human (subagent-parallelizable to ~30 min wall clock).

---

### F4 — 🟡 HIGH: Cron-failure observability is opt-in (asymmetric with success path)

**Where:** `keel/scheduling/decorators.py` — exception path
**Evidence:** the `emits=` wrapper in `keel/scheduling/decorators.py` auto-emits a `record_system_event` call on success (when handle() returns a structured dict), but on exception writes only the CommandRun row with status='error'. No Activity row is created, so `dispatch_activity_notifications` doesn't fire and `system_admin`s get no notification.

**Why this matters:** silent cron failures are the original problem this whole plan was meant to solve. The canary's `cron_failures_24h` flag eventually catches it (15-min poll cadence), but staff don't get a push notification when their cron dies — they have to open `/scheduling/` or `/ops/` proactively. Asymmetric defaults are also surprising: success auto-emits, failure doesn't.

**Fix:** in `keel/scheduling/decorators.py`, add a try/except around `original_handle(self, *args, **opts)` that, on exception, calls `record_system_event(verb=emits, summary=f"{slug} failed: {exc}", status='failed', metadata={'exception_type': type(exc).__name__})`. Then re-raises. ~20 lines of keel code + a test. Resolves both the silent-failure problem and the asymmetric-default surprise.

**Effort:** ~30 min in keel.

---

### F5 — 🟡 MEDIUM: Activity model location drift in 2 products

**Where:**
- `beacon`: Activity is split across `beacon/pipeline/models.py` (pipeline-specific) AND `beacon/interactions/activity_models.py` (interactions-specific).
- `helm`: Activity is split across `helm/tasks/activity_models.py` AND `helm/dashboard/activity.py`.

**Why this matters:** the Activity contract is "one concrete subclass per product." Splitting it across multiple files (and potentially multiple model classes if there's more than one inheriting from AbstractActivity) means:
- `KEEL_ACTIVITY_MODEL` setting can only point at ONE — which one is canonical?
- `record_activity()` / `record_system_event()` resolve via `settings.KEEL_ACTIVITY_MODEL` — calls from "the other" model's domain may write to the wrong table.
- `fetch_product_activity` aggregator pulls from one endpoint per product — drift means partial data.

**Fix:** read both files in beacon and helm; confirm whether this is two different concrete subclasses (real drift, needs consolidation) or one model + a service-layer file colocated nearby (just naming, not actual drift). If genuine drift, consolidate to a single canonical Activity per product.

**Effort:** ~30 min investigation per product; consolidation effort depends on what's found (could be 1 hour or could be a day if there are real two-table data integrity issues).

---

### F6 — 🟢 LOW: Notification preferences are per-product (no cross-product mute)

**Where:** every product has its own `NotificationPreference` model inheriting from `AbstractNotificationPreference`.

**Why this matters:** a user who mutes "task assigned" notifications in Helm doesn't mute the same notification type in Bounty. As the user base grows, this becomes annoying.

**Fix:** Phase 2 work. Move NotificationPreference to keel as a concrete model and have products query the suite-wide row. Non-trivial because it requires a cross-product user-preference store and an SSO bridge (OIDC claim?) to propagate.

**Effort:** ~1 week. Defer until users complain.

---

### F7 — 🟢 LOW: 114 `register_audited_model` registrations across 9 products

**Where:** 114 model registrations in `register_audited_model` calls (Harbor 28, Lookout 25, Beacon 18, etc.)

**Why this matters:** under the v0.46.3 user gate, these are all SAFE — system mutations are silently skipped. But the registry is heavy: every audited model is a post_save+post_delete signal connection at boot. Some models registered may not actually need audit (e.g., admin-only models nobody mutates outside dev).

**Fix:** per-product audit pass: `grep register_audited_model` → identify models never mutated outside admin → consider removing the registration. Low value; only worth doing if startup time becomes a problem.

**Effort:** ~1 hour per product if anyone cares. Probably never worth doing.

---

### F8 — 🟢 INFO: `keel.ops` has no console, only canary

**Where:** `keel/ops/`
**Evidence:** `keel/ops/views.py` only exposes `canary_view`. No template, no console.

**This is by design** — the plan called for `/ops/` to be a new keel-level surface; nobody has built it yet. F2 is the same finding from a different angle. Listing here only so the architecture map is honest.

---

### F9 — 🟢 INFO: Watcher-based notifications are present but rarely used

**Where:** `AbstractWatcher` in `keel/activity/models.py`; product Watcher subclasses.

**This is by design** — Watchers are an opt-in subscription primitive for users who want notifications on specific records or verbs. Adoption is low in v1 (users mostly rely on collaborator-based fan-out). Not a bug, just a low-utilization corner.

---

## Recommendations — Priority Queue

Ranked by impact-per-hour-of-work. If you only do three things:

### 🥇 Priority 1: Close F1 + F2 + F3 as a coordinated rollout (~1 week total)

These three together deliver the `/ops/` console as a working product surface, end-to-end. Sequencing:

**Day 1 (keel PR):**
- Add `check_activity_feed_wiring` boot check (warns if a product is missing the mount)
- Add cron-failure auto-emit in `@scheduled_job` decorator (F4 closed for free)
- Build thin `/ops/` console view: 3 rows, reuse `/audit/` template patterns
- Bump keel to v0.56.0, tag, push

**Day 2 (product PRs, parallelized):**
- 9 PRs in parallel via subagents: mount `/api/v1/activity-feed/` + add `emits='verb.name'` to primary cron(s)
- Each PR: bump keel pin to v0.56.0 + mount endpoint + annotate cron

**Day 3 (verification):**
- Open `keel.docklabs.ai/ops/` as dokadmin
- Verify all 9 product chips are green on Row 2 (system events)
- Trigger a synthesized `record_system_event(verb='test.failed', status='failed', ...)` from a product shell
- Confirm in-app + email notification arrives

**Outcome:** Dan opens `/ops/` daily; cron failures push notifications; the whole Approach D vision is realized in user-visible form for the first time.

### 🥈 Priority 2: Investigate F5 (Activity model drift in beacon + helm) — ~1 hour

Cheap to investigate, important to know. If real drift, consolidate. If naming confusion, document.

### 🥉 Priority 3: Skip F6, F7, F9 until they bite

Notification preferences (F6) wait until cross-product mute is a real ask. Auto-audit registry pruning (F7) wait for a startup-time problem. Watcher adoption (F9) wait for users requesting opt-in subscriptions.

---

## What's Working Well (don't break)

A code review that only surfaces problems is incomplete. Several things in this subsystem are genuinely well-designed and should not be touched:

- **The Track A / Track B / system-event split** — three clear modes for "audit triggered by save", "explicit user action with rich metadata", "system summary." Clean mental model.
- **The user gate at the signal layer** — one early-return in `_on_save` eliminated a whole class of bloat. Conceptually small, structurally load-bearing.
- **The `audit_context` context manager** — escape hatch for Celery/shell/migrations without making the gate optional. Composes naturally with `with` statements.
- **Declarative `@scheduled_job(emits='verb.name')`** — handler returns a dict; decorator emits. Removes social-enforcement risk (lazy summaries) by design.
- **The `audit_feed_view` / `activity_feed_view` symmetry** — two near-identical decorators with distinct cache namespaces. Easy to mirror for new feed kinds.
- **The notification visibility gate** — `Activity.is_visible_to_user()` runs BEFORE every notification fires. This is what makes stub-tier activity rows safe to dispatch (Beacon's zone-bridge requirement). Not negotiable.
- **The schema constraint on `AuditLog.user`** — Django `null=False` + DB `CheckConstraint`. Schema-defensible "what users did". The plan's ambition realized.

---

## Open Questions for Dan

1. **Is the `/ops/` console worth ~1 week of work** to ship the three findings together (F1+F2+F3+F4)? Alternative: ship just F1 (`/api/v1/activity-feed/` mounts) and defer `/ops/` until you actually want to look at it.
2. **Cron-failure notification policy** — when a cron fails, who gets paged? Plan default was `system_admin`s of that product. Confirm or adjust before F4 ships.
3. **Activity model drift in beacon + helm** — would you rather I investigate now (~30 min each) or batch with the F1/F2/F3 rollout?
4. **`/ops/` audience** — staff only, or also `agency_admin`s? The canary uses superuser-or-system_admin; `/ops/` could use the same gate or open to a broader staff audience.
5. **System-event retention** — Activity rows with `actor IS NULL` accumulate. The plan called for a 90-day purge command. Not yet built. Bounty's hourly poll → ~2160 rows/year. Trivial volume; build when bored.

---

*End of review.*
