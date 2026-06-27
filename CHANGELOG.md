# Keel Changelog

Notable changes per release. Newest first. During development, changes are added
as fragments under `changes.d/`; `scripts/release.py cut` collates them into a
new section here and bumps + tags the version. See `changes.d/README.md` and the
"Keel releases" section in `CLAUDE.md`.

## 0.56.1 — 2026-06-27

**Annotate keel-shipped retry_failed_mention_deliveries cron with @scheduled_job(emits=) so consumers (harbor) inherit /ops/ visibility + failure notifications for free.**

### Added
- **`keel-mentions-retry-failed-deliveries` cron annotated with `@scheduled_job(emits='keel_mentions.failed_deliveries_retried')`.** Every consumer of `keel.mentions` (currently harbor) inherits both scheduling-registry visibility AND `/ops/` Activity emission for free. The cron returns a structured dict with `{attempted, ok, failed, gone}` counters; `status='warn'` when any row failed/was-gone, `'ok'` otherwise. Closes a follow-up from the 2026-06-27 review: keel-owned crons that ship to consumers should be annotated at the source so each consumer doesn't need to wire `emits=` separately.

## 0.56.0 — 2026-06-27

**Cross-product /ops/ console — Activity system-events lane fan-out, scheduling, canary. New keel_site.ops app.**

### Added
- **Changelog fragments + `scripts/release.py`.** Develop by dropping a `changes.d/<slug>.<category>.md` fragment; cut releases with `release.py cut <part>` (collates fragments, bumps both version files, commits, tags, pushes). Replaces the per-commit `__version__` bump rule, which made parallel keel branches collide on the version number and the top of CHANGELOG.md.
- **Keel `/ops/` console** — cross-product operational console at `keel.docklabs.ai/ops/`. Three rows: scheduling (Keel-local in v1) / Activity system-events lane (cross-product via `fetch_product_activity`) / canary (Keel-local in v1). Same permission gate as `/audit/` (superuser OR system_admin/agency_admin ProductAccess). New `keel_site.ops` app holds the aggregator, forms, permissions, and template; mounted at `path('ops/', OpsConsoleView.as_view(), name='ops')`. Products that haven't mounted `/api/v1/activity-feed/` yet show as gray 'pending' chips — that's the visible signal to wire the endpoint.

### Changed
- **`CLAUDE.md` release rule rewritten** to fragments + one-step cut + tag-pinning (was: bump `__version__` every commit). The pip cache trap is now defeated by immutable tags, not per-commit bumps.

## 0.55.0 — 2026-06-25

**Reconcile the divergent `v0.54.x` release line with `main`.** The `v0.54.0`–
`v0.54.2` tags branched off `v0.52.3` and never received two fixes that had
landed on `main`: the fleet-switcher full-opacity override (`v0.52.4`) and the
`keel.requests` admin-scope security fix (`v0.53.1`). Any product pinning a
`v0.54.x` tag therefore rendered greyed-out fleet logos and shipped the
cross-product `_admin_check` hole. This release carries **both** lines: every
`v0.54.x` workflow/CSS fix **and** the two `main`-only fixes, cherry-picked onto
the `v0.54` tip. `0.55.0` is the single line going forward — pin all products
here.

### Fixed
- **Fleet switcher renders v3 brand tiles at full opacity** (cherry-picked from
  `v0.52.4` / `9ad48e6`). `.fleet-logo-chip img` and `.sb-icon.fleet-icon-img`
  override the nav-glyph dimming so the full-color navy `#0A2B4E` tiles no
  longer wash out to grey. Only the monochrome glyph fallback stays recessed.
- **`keel.requests` `_admin_check` is scoped to the current product**
  (cherry-picked from `v0.53.1` / `502fdcb`). The change-request admin console
  now requires `is_superuser` OR an active `system_admin` `ProductAccess` for
  `get_product_code()`, instead of any product's `admin`/`system_admin` — closing
  the peer-mount approval hole flagged by the `/cso` audit.

### Included (from the `v0.54.x` line)
- `v0.54.2` — multi-line `{# … #}` comment conversion + centralized CI guard
  (`5f260db`).
- `v0.54.1` — readable `.text-bg-info` (white text) + `.pill-submitted_for_approval`
  alias (`5d7adc0`).
- `v0.54.0` — Django 6.0 compatibility: `CheckConstraint(condition=…)`, Django
  upper cap dropped (`b836c7c`).
- `v0.53.0` — invitation CC, beta-tester callout, AI-key walkthrough + CC-me
  checkbox test coverage (`0e335d4`, `5ee3785`).

## 0.54.1 — 2026-06-23

**Fix unreadable `text-bg-info` pills (dark-on-dark).**

Section 2 remaps `--bs-info-rgb` from stock Bootstrap's light cyan to a dark
navy (`#2C5F8D`). Bootstrap's `.text-bg-info` utility bakes in `color: #000` at
compile time — chosen against the *original* light cyan — so the remap silently
left black text on a dark navy background (contrast 3.1, unreadable). Surfaced
as the "grants.gov" source pill on bounty's opportunities list, which renders
`<span class="badge rounded-pill text-bg-info">`.

The existing `.pill.bg-*` correction (section 21) only covers keel's own `.pill`
component, never Bootstrap's `.text-bg-*` utility — which is why this recurred.

### Fixed
- **`.text-bg-info` now forces `color: #fff`** (`keel/core/static/css/
  docklabs-v2.css`), colocated with the `--bs-*-rgb` remap that causes the
  mismatch. Info is the only utility that flips: warning's brass keeps readable
  black; primary/secondary/success/danger stay white, matching Bootstrap.

### Added
- **`.pill-submitted_for_approval` status-pill alias** (brass/review group in
  `docklabs-v2.css`), for products with an explicit "submit for approval"
  workflow gate (Bounty's OpportunityClaim). Renders the same brass treatment
  as `.pill-submitted` / `.pill-pending`.

## 0.54.0 — 2026-06-22

**Django 6.0 compatibility: drop the last `CheckConstraint(check=...)`.**

Django 6.0 removed the deprecated `check=` kwarg on `CheckConstraint` (renamed
to `condition=` in 5.1). One abstract base — `AbstractAuditLog` — was still on
`check=`, so the moment a consumer's environment resolved Django 6.0.x, *every*
keel import died at class-definition time with `TypeError: CheckConstraint.
__init__() got an unexpected keyword argument 'check'`. Hit live in helm, whose
venvs had pulled Django 6.0.3 because an older keel pin predated the `<6.0` cap.

### Fixed
- **`AbstractAuditLog` now uses `condition=` instead of `check=`** (`keel/core/
  models.py`). This was the only remaining `check=` site in keel source; all
  other models (`KeelUser`, `MentionDelivery`, `keel.accounts.AuditLog`) and all
  migration files already used `condition=`. The flip is **migration-churn-free**:
  Django 5.1+ stores both kwargs as `self.condition` and `deconstruct()` emits
  `condition=` regardless, so consumers' concrete `AuditLog` subclasses
  deconstruct identically and `makemigrations` detects no change.

### Changed
- **Django upper cap removed — pin is now `Django>=5.2`** (was `<6.0`). keel
  tracks the current Django; 5.2 is the floor (oldest tested release). Verified
  against **Django 6.0.6**: `manage.py check` clean, `makemigrations --check`
  reports no changes, and the full keel test suite (472 tests) passes
  identically to 5.2.13. When a future Django major lands, test keel against it
  rather than re-adding a ceiling.

### Consumer note
- A product whose *own* concrete `AuditLog` migration file was generated under
  Django ≤5.0 may still serialize `check=` in that committed migration, which
  Django 6.0 also rejects when loading. That's outside keel — regenerate or
  hand-edit the offending migration to `condition=` if it surfaces.


## 0.53.0 — 2026-06-22

**Invitation email enhancements: optional CC, beta-tester callout, and a
bring-your-own AI-key walkthrough.**

### Added
- **TEMPORARY "CC me" checkbox on invitations.** The invite matrix form has a
  `cc_me` checkbox; when ticked, the invitation email is CC'd to the hardcoded
  beta address `dok@dok.net` so Dan can see exactly what a beta invitee
  receives. No free-form CC field — the address is fixed to the superuser, so
  there's no way to misdirect the accept token. No model field and no
  migration; the address lives in a `_BETA_CC_EMAIL` constant in
  `keel/accounts/views.py`. **Remove the checkbox + constant once invites go to
  real customers.**
- **Beta-tester section in the invitation email.** When any product in the
  batch grants beta-tester status (`any_beta`), the email tells the invitee
  they're a beta tester and to submit feedback via the bottom-right feedback
  button (the `keel.requests` widget).
- **AI bring-your-own-key walkthrough.** When any product in the batch grants
  AI access (`any_ai`), the email walks the invitee through creating an
  Anthropic account, adding billing, generating an API key, and pasting it
  into their AI settings (`/settings/?panel=ai`). Both HTML and plaintext
  bodies updated; sections are omitted entirely when their flag is unset.

## 0.52.4 — 2026-06-23

**Render the fleet switcher's brand tiles at full opacity (navy, not grey).**
The fleet switcher dimmed its chip images to `opacity: 0.55` (collapsed rail) and
inherited `opacity: 0.7` from `.sb-icon` (expanded list). That treatment was
designed for the old faint monochrome glyphs; against the v3 full-color navy
tiles it washed the navy `#0A2B4E` out to a muted grey-blue, so the refreshed
logos read as "old / greyed-out." Verified in a headless browser: the SVGs load
200 and render correctly, but the dimming made them look grey.

### Fixed
- `.fleet-logo-chip img` now renders at `opacity: 1`; only the monochrome glyph
  fallback (`.fleet-logo-chip > i`, for products without an SVG) stays recessed.
- `.sb-icon.fleet-icon-img` overrides the nav-glyph `opacity: 0.7` so the
  expanded-list brand tiles also render at full strength.

## 0.52.3 — 2026-06-22

**Render the v3 fleet marks in the brand chrome, not just the fleet switcher.**
The v0.52.0 logo refresh updated `img/fleet/*.svg`, but the prominent brand
surfaces — the top-left sidebar brand, the public top-bar brand, and the
login-card hero — still rendered a per-product **Bootstrap glyph**
(`bi-bank2`, `bi-hexagon`, …), so the suite still looked like the old UI. Those
three surfaces now render the current product's `img/fleet/<code>.svg` (resolved
from `CURRENT_PRODUCT` = `KEEL_PRODUCT_CODE`), matching the fleet switcher.

### Changed
- **`app.html`, `public.html`, `components/sidebar.html`** — `.sidebar-brand-icon`
  now renders `<img class="sidebar-brand-img" src="…/fleet/<code>.svg">` filling
  the tile (the SVG's navy field becomes the tile).
- **`login_card.html`** — the hero icon now renders the fleet mark.
- Each surface keeps the per-product Bootstrap glyph as an `onerror` fallback
  (same pattern as the fleet switcher), so a missing SVG degrades gracefully and
  the `sidebar_brand_icon` block products already set still works. A new optional
  `sidebar_brand_code` block lets a product override the mark's product code.
- **`docklabs-v2.css`** — adds `.sidebar-brand-img` / `.login-brand-img` sizing;
  `.sidebar-brand-icon` gains `overflow: hidden` to clip the mark to the tile.

No per-product template changes required — products inherit the marks by bumping
their keel pin to v0.52.3.

## 0.52.2 — 2026-06-22

**Wire PNG + apple-touch favicon fallbacks into the shared `<head>`.** Completes
the v0.52.0/v0.52.1 brand refresh: products now ship per-product `favicon.svg` +
`favicon-32.png` + `apple-touch-icon.png`, but the shared layouts only referenced
the SVG. This adds the two missing `<link>` lines so old browsers get a PNG
favicon and iOS home-screen bookmarks get a proper touch icon.

### Added
- **`<link rel="icon" type="image/png" sizes="32x32" href="img/favicon-32.png">`**
  and **`<link rel="apple-touch-icon" href="img/apple-touch-icon.png">`** in the
  three shared layouts (`app.html`, `public.html`, `auth.html`), alongside the
  existing SVG favicon link.
- **keel default `favicon-32.png` + `apple-touch-icon.png`** in
  `keel/core/static/img/` (the Keel hull mark) so a product that hasn't shipped
  its own PNGs falls back to a Keel-branded icon instead of a 404 — same
  override pattern as the existing `favicon.svg`.

### Migration
- Re-pin `keel @ git+https://github.com/okeefedaniel/keel.git@v0.52.2`. Products
  that already shipped `static/img/favicon-32.png` + `apple-touch-icon.png` (the
  v3 favicon PRs) need no other change; the new `<head>` links resolve to those
  per-product files. `collectstatic` + cache-bust on deploy.

## 0.52.1 — 2026-06-22

**Deliver the CSP inline-style fix on top of the v0.52.0 fleet-logo refresh.**
v0.51.3 (CSP fix) and v0.52.0 (logo refresh) shipped as divergent siblings off
`7cb1dc5`; products adopted v0.52.0 and so were missing the CSP fix. This release
merges both lines so consumers get the new logos AND the CSP-clean chrome from a
single tag. No functional change beyond the union of the two — see the 0.52.0 and
0.51.3 entries below for details. Re-pin
`keel @ git+https://github.com/okeefedaniel/keel.git@v0.52.1` in each product.

## 0.51.3 — 2026-06-22

**Stop the suite-wide CSP inline-style console violations.** Every authenticated
page across the suite logged repeated "Applying inline style violates the
following Content-Security-Policy directive" warnings: the shared chrome carried
static inline `style=""` attributes, and a CSP nonce can authorize a `<style>` /
`<script>` *element* but NEVER an inline `style=""` *attribute*. Under a strict
`style-src` (no `'unsafe-inline'`), those attributes were silently dropped on
every render. Fixed by moving the static inline styles into CSS classes in the
shared `docklabs-v2.css` rather than relaxing the policy — no `'unsafe-inline'`
added, XSS protection unchanged.

### Fixed
- **Shared layouts** (`app.html`, `public.html`, `auth.html`): skip-link
  `z-index`, search-icon sizing, and the auth-shell background/min-height now use
  `.dl-skip-link`, `.dl-search-icon`, `.dl-auth-body`.
- **Shared chrome** (`sidebar.html`, `topbar.html`): search-icon sizing →
  `.dl-search-icon`.
- **Shared components** (`quick_info`, `collaborator_list`, `comment_section`,
  `canary_flags`, `collaboration_panel`, `workflow_transitions`): metadata
  labels → `.dl-meta-label`, avatars → `.dl-avatar-sm` / `.dl-avatar-md`, canary
  chips → `.dl-chip-xs`, collapsed-panel summary cursor and transition-control
  widths → dedicated classes.
- **`chart.html`**: the per-instance (dynamic) chart height now ships through a
  nonce'd `<style>` element scoped to the chart id — the CSP-clean path for
  legitimately-dynamic styling — instead of an inline `style=""` attribute.

### Notes
- Email templates (`accounts/emails/`) intentionally keep inline styles — mail
  clients strip `<head>`/`<style>` and require inline styling, and CSP does not
  apply to rendered email. The accounts auth/invitation pages still carry some
  brand-color one-offs; those are a smaller, lower-frequency follow-up.

## 0.52.0 — 2026-06-22

Fleet logo refresh (v3 "Civic Institution").

### Changed
- **New fleet logo set.** Replaced all product marks in
  `keel/core/static/img/fleet/*.svg` with a redesigned, cohesive set: navy field
  (`#0A2B4E`, the v3 institutional navy — was `#00214D`), a paper-white maritime
  mark (1.6px stroke, round joins), and exactly one luminous-brass accent
  (`#D8A43C`) per mark. Marks read down to 20px (the fleet-switcher chip size).
  - Helm (ship's wheel), Harbor (portico/treasury), Beacon (lighthouse),
    Lookout (binoculars), Bounty (globe), Admiralty (shield + key),
    Purser (strongbox), Manifest (document + signature), Yeoman (calendar),
    Keel (hull frame).
- Added `fleet/docklabs.svg` — a suite/master mark (dock + waterline) for
  marketing and cross-product surfaces.

### Added
- Per-product favicon assets (`<product>/static/img/favicon.svg` + 32px / 180px
  PNG fallbacks) derived from each product's new mark. These ship in per-product
  repo PRs, not keel — see `MIGRATION.md` in the asset bundle.

### Migration
- No template changes required: the fleet switcher and dashboards already resolve
  `img/fleet/{code}.svg` by product code, and filenames are unchanged.
- Re-pin `keel @ git+https://github.com/okeefedaniel/keel.git@v0.52.0` in each
  product's `requirements.txt`. Run `collectstatic` and cache-bust on deploy.
- Rollback is a static-asset revert + prior keel tag re-pin — no data or
  template migration.

## 0.48.2 — 2026-05-28

**Two consumer-blocking bugs in the v0.48.0 Approach D rollout.** Both surfaced
when Bounty became the first product to adopt the new audit/activity pattern —
they would have tripped every one of the remaining 7 product retrofits.

### Fixed
- **E032 constraint-name collision (every consumer's `makemigrations` failed).**
  `AbstractAuditLog.Meta.constraints` hardcoded `name='auditlog_user_required'`.
  Django requires constraint names to be globally unique across all models in a
  project. The moment a consumer's concrete `AuditLog(AbstractAuditLog)` inherited
  that constraint AND `keel.accounts.AuditLog` also carried one, `makemigrations`
  aborted with `models.E032`. The abstract name is now TEMPLATED
  (`%(app_label)s_%(class)s_user_required`) so each concrete subclass gets a
  unique name (`bounty_core_auditlog_user_required`, etc.). `keel.accounts.AuditLog`
  keeps its existing explicit `auditlog_user_required` name so its already-applied
  migration `0022` needs no rename. **Consumers no longer need to override the
  constraint name** — inherit and move on.
- **`@scheduled_job(emits=...)` crashed every emitting cron at runtime.** The
  decorator returned the handler's structured dict, which Django's
  `BaseCommand.execute()` passes to `self.stdout.write()` →
  `AttributeError: 'dict' object has no attribute 'endswith'`. The wrapper now
  returns `None` on the `emits` path (after consuming the dict for the Activity
  row). Non-emits commands keep returning their `handle()` value unchanged.
  **Consumers no longer need a custom `Command.execute()` override.**
- **`@scheduled_job` crashed when `keel.scheduling` wasn't in `INSTALLED_APPS`.**
  The lazy `from keel.scheduling.models import …` ran outside the try/except, so a
  consumer that forgot to add the app got a `RuntimeError` that killed the cron
  instead of the intended graceful "no run-log" degradation. Import moved inside
  the try. (Adding `keel.scheduling` to `INSTALLED_APPS` is still required to get
  `CommandRun` observability — it just no longer hard-crashes without it.)

### Changed
- **`audit_constraint_present` canary now checks column nullability, not the
  constraint name.** Since the constraint name is templated per-product, a
  name-based `information_schema` lookup would need each product's app_label.
  The gauge now queries `information_schema.columns.is_nullable` on the AuditLog
  `user_id` column — the actual protection, name-independent, more robust.

## 0.48.1 — 2026-05-21

**Packaging fix — `keel.accounts` static files now ship in the wheel.** The
`/settings/account/` page in every product loaded a broken `<script src="…/keel/accounts/js/username-check.js">` because that file existed in source but was excluded from the built wheel: `pyproject.toml`'s `[tool.setuptools.package-data]` list for `keel.accounts` was missing the `static/**/*` glob. Three sibling packages with static dirs (`keel.core`, `keel.search`, `keel.mentions`) include it; `keel.accounts` was the only gap. Caught by lookout's nightly QA agent on its first run.

### Fixed
- `pyproject.toml`: add `"static/**/*"` to `keel.accounts` package-data so the
  username-availability JS (and any future static assets under `keel/accounts/static/`)
  ships in the wheel. Existing static dirs in `keel.core`, `keel.search`, and
  `keel.mentions` were already wired correctly — this brings `keel.accounts` in line.

## 0.48.0 — 2026-05-20

**Audit / Activity / Notifications rethink — Approach D ships.** Forced by Bounty's
audit-log disk exhaustion (2026-05-18: `bounty_core_auditlog` at 2368 MB / 98% of DB;
1.27M rows, 99.996% with `user_id IS NULL` from cron-driven `update` events). Approach
D commits to schema-enforced separation: `AuditLog` becomes the legally defensible
"who did what" log with `user NOT NULL`; `Activity` becomes the canonical "what
happened" stream including system events. See the parallel plan at
`~/.claude/plans/audit-activity-notifications-rethink.md` for the full design.

### Added
- **`AbstractAuditLog.user` is now `null=False, on_delete=PROTECT`** with a
  `CheckConstraint(check=Q(user__isnull=False), name='auditlog_user_required')`
  for defense in depth (DB-level enforcement matching the Django-level constraint).
  `keel.accounts.AuditLog` (concrete subclass) mirrors the constraint on its own
  `Meta.constraints` because Django doesn't propagate `Meta.constraints` from
  abstract bases to concrete subclasses.
- **Source-scoped verb catalog** in `keel/activity/verbs.py` — 12 new verbs:
  `grants_gov.polled`, `salesforce.synced`, `openstates.polled`, `foia.cache_refreshed`,
  `invitations.pulled`, `webhook.retried`, `health.computed`, `tasks.notified`,
  `auth.login_failed`, `auth.login_succeeded`, `security.account_locked`,
  `security.suspicious_activity`. Each defaults to `default_visibility='staff'`,
  `default_notify=False`. `VERB_DESCRIPTIONS` dict for `/ops/` tooltip rendering.
- **`audit_constraint_present` canary gauge** in `keel.ops.canary` — queries
  `information_schema.check_constraints` for the `auditlog_user_required` constraint
  on the AuditLog table. Three-state gauge (True / False / None). Flag triggers
  only on explicit False (gauge measured + constraint absent). None on non-postgres
  or query failure → flag stays False (no false positives).
- **Per-product `AuditLog.user` NOT NULL migration** —
  `keel/accounts/migrations/0022_auditlog_user_required.py` alters
  `keel.accounts.AuditLog.user` to NOT NULL + PROTECT, adds the CheckConstraint,
  drops `LOGIN_FAILED` and `SECURITY_EVENT` from `Action` choices. **Migration is
  self-gating:** if any product (or keel's own AuditLog) has `user_id IS NULL`
  rows at apply time, it raises `NotNullViolation` and the deploy fails loudly.
  This is the desired safety net.

### Changed
- **Failed-login + security events route to Activity, not AuditLog.**
  `FailedLoginMonitor._record_failure` emits `auth.login_failed` (status=warn) on
  every recorded failure. Lockout threshold trip emits `security.account_locked`
  (status=failed) so the Activity → Notification seam fans the row out to product
  `system_admin`s. `AdminIPAllowlistMiddleware` emits `security.suspicious_activity`
  (status=warn) on 403. All emission paths wrapped try/except — a broken Activity
  write never breaks the middleware's primary job. Successful logins still write
  `AuditLog(action='login', user=actual_user)` — they naturally satisfy the
  `user NOT NULL` constraint.
- **`keel.security.alerts.check_failed_logins`** rewritten to read Activity
  (`verb='auth.login_failed'`) by default when `KEEL_ACTIVITY_MODEL` is configured,
  with legacy-AuditLog fallback for mid-rollout products / existing tests.
  Signature backwards-compatible.
- **`AbstractAuditLog.Action.choices`** drops `LOGIN_FAILED` and `SECURITY_EVENT`
  (now Activity verbs).

### Breaking changes (consumer action required)
**Before bumping the keel pin in any product:**
1. **Prune null-user audit rows.** Run on each product's database:
   ```sql
   SELECT count(*) FROM <product>_core_auditlog WHERE user_id IS NULL;
   -- If > 0, prune via copy-and-swap (parallel plan §3.4):
   BEGIN;
   CREATE TABLE <product>_core_auditlog_keep AS
     SELECT * FROM <product>_core_auditlog WHERE user_id IS NOT NULL;
   TRUNCATE <product>_core_auditlog;
   INSERT INTO <product>_core_auditlog SELECT * FROM <product>_core_auditlog_keep;
   DROP TABLE <product>_core_auditlog_keep;
   COMMIT;
   ```
   `TRUNCATE` is sub-second `ACCESS EXCLUSIVE` lock; no `VACUUM FULL` needed
   (deallocates physical pages directly). Bounty's prune is the only one with
   significant row volume; other products should be <1000 rows total each.
2. **After pruning, run `manage.py makemigrations`** to generate the per-product
   `AlterField` migration that propagates NOT NULL + CheckConstraint to the
   product's concrete `AuditLog` subclass. Apply with `manage.py migrate`.
3. **Rewrite bulk-upsert crons** to use the existing
   `@scheduled_job(emits='verb.name')` decorator from `keel.scheduling` and return
   a structured dict from `handle()` (see `keel.activity.services.record_system_event`).
   Bounty's `sync_federal_grants` is the reference consumer.
4. **Note:** `keel_site/dashboard.py:76-82` queries `AuditLog.objects.filter(action__in=['login_failed', 'security_event'])`
   for a "security events this week" stat. Those queries now return 0 since no
   new rows of those action values can be written. UI fix is part of the Phase 4A
   `/ops/` redesign (separate session), not this release.

## 0.47.2 — 2026-05-20

**Fix `_fan_out` calling `notify()` with kwargs that don't exist.** Notification
fan-out from `record_activity()` silently failed for every workflow transition
in v0.47.0 / v0.47.1. `keel.activity.dispatch._fan_out` called
`notify(user=..., notification_type=..., label=..., activity=...)`, but the
real signature is `notify(event=..., recipients=..., title=..., link=...)`.
Both the primary call and the TypeError fallback used the wrong kwargs, so
every call raised `TypeError` and was swallowed by the outer `except Exception`
— no notifications fired from any product since v0.47.0.

### Fixed
- `keel.activity.dispatch._fan_out` now calls `notify()` with `event=`,
  `recipients=[user]`, `title=activity.source_label`, `link=activity.deep_link`.
- Removed the stale `except TypeError` fallback — once the signature is right,
  TypeError is a programmer error, not a runtime branch.
- Dropped the `activity=activity` kwarg; `notify()` doesn't support
  `activity_ref` population. Tracked as a follow-up.

### Added
- `keel/activity/tests/test_dispatch.py` — regression coverage for the call
  shape, the loop-per-user behavior, and the swallow-exceptions contract.

## 0.45.0 — 2026-05-16

**Fix the ops canary `is_staff` leak suite-wide.** The historical gate
(`{% if user.is_staff and canary %}` on dashboards, `@staff_member_required`
on `/api/v1/metrics/`) was too loose: `seed_keel_users` force-sets
`is_staff=True` on every demo user so the Django admin works for every
role flavor, which meant every demo agency_admin / analyst / reviewer
saw ops infrastructure on their dashboard. Per the suite role rule, only
Django superuser or product `system_admin` should bypass admin-only UI.

### Added
- `keel.ops.canary.user_can_view_canary(user)` — single helper that
  resolves `KEEL_PRODUCT_CODE` and checks for superuser or
  `system_admin` `ProductAccess`. Re-exported from `keel.ops`.

### Changed
- `keel.ops.views.canary_view` — session-auth fallback now calls
  `user_can_view_canary` and returns `HttpResponseForbidden` when
  denied, instead of `@staff_member_required` which redirected to
  admin login. Bearer-token path (`KEEL_METRICS_TOKEN`) unchanged.
- `keel/CLAUDE.md` "Ops canary" section — documents the helper, the
  `{% if canary %}` template pattern, and the demo `is_staff` rationale.

### Migration for consumers
Helm and Lookout are the only adopters today. Both update to gate on
`user_can_view_canary(user)` in the dashboard view and drop `user.is_staff`
from the template. Future adopters: gate the view (set `canary` in context
only when the helper returns True) and keep the template dumb (`{% if canary %}`).

## 0.44.1 — 2026-05-16

**Post-/review hardening of Wave 1 batch 1.** Codex adversarial review surfaced
seven findings against the 0.40.2 / 0.41.1 / 0.41.2 / 0.44.0 commits (this
session's Wave 0 + Wave 1 batch 1 work). Two AUTO-FIXED in template behavior;
three became durable docstring/CLAUDE.md updates; one (visibility-contract
docstring tightening on three templates) was applied per user choice on the
metadata-leak finding; one (`render_for` target removal) skipped after audit
confirmed no known consumers.

### Fixed
- `quick_info.html` extra_fields used `|default:"—"` which corrupts valid
  falsey values (`0`, `False`, empty string). Switched to `|default_if_none:"—"`
  so only `None` collapses to the dash. Caught by Codex.
- `workflow_transitions.html` docstring told callers to compute transitions via
  `entity.WORKFLOW.get_available_transitions(user)` — but that's the engine's
  signature which takes `current_status` first, not `user`. Following the docstring
  would silently produce no workflow buttons. Corrected to point at the mixin
  method `entity.get_available_transitions(user)`. Caught by Codex.

### Documentation
- `keel/activity/models.py` `render_for` docstring now clarifies that
  `select_related('target_ct')` on the queryset (as `activity_panel` does) only
  avoids the ContentType lookup; it does NOT prefetch the target object.
  Subclasses that re-expose `self.target` need Django 4.2+ `GenericPrefetch` for
  true zero-N+1 behavior. Caught by Codex.
- `keel/CLAUDE.md` "Keel Integration (Minimum Required)" now explicitly lists
  `django.contrib.humanize` as a required `INSTALLED_APPS` entry. Shared keel
  templates have always `{% load humanize %}` but the convention was implicit.
  Adopting the new collaboration_panel will crash with `TemplateSyntaxError`
  in any product that doesn't have it. Caught by Codex.
- `keel/CLAUDE.md` "Object-scoped roles" section now extends the obj= contract:
  subclasses of `WorkflowEngine` that override `get_available_transitions` or
  `can_transition` MUST accept `obj=None`. The existing rule only covered
  `_user_has_role`. None of the current product engines override these methods
  (verified), but the contract change in 0.40.2 deserves documentation.

### Known issue (deferred — user decision pending)
- `comment_section.html`, `attachment_list.html`, and `collaboration_panel.html`'s
  collapsed-mode summary all show counts (`{{ comments|length }}` etc.) computed
  against the INPUT queryset, BEFORE the per-row internal-visibility guard runs.
  If a caller forgets view-level filtering, non-staff users don't see internal
  row contents but they DO see "Comments (5)" when only 3 are visible — a
  metadata leak. The defensive filter was designed as second-line defense; the
  primary contract is caller-side filtering. Fix options under discussion: (a)
  drop the count badge entirely, (b) require optional `total_count` kwarg, (c)
  document the contract more aggressively in template comments. Caught by Codex.

## 0.44.0 — 2026-05-15

**Wave 1 (collaboration-panel) batch 1.** The orchestrator + the two
missing sub-includes ship. Wave 2 (Yeoman adoption) can now consume
this in its detail page.

### Added
- `keel/core/templates/keel/components/collaboration_panel.html` — the
  Wave 1 orchestrator. Composes five existing keel/components/ sub-includes
  in fixed order: claim_row → collaborator_list → comment_section →
  workflow_transitions → attachment_list. Sub-sections opt out by
  omitting their data kwarg (e.g. don't pass `notes` to skip the
  discussion section). Supports `collapsed=True` for the Admiralty
  carve-out: wraps the whole panel in a `<details>` element with a
  single-line summary showing claim state + member/note/file counts.
- `keel/core/templates/keel/components/attachment_list.html` — renders
  an `AbstractAttachment` queryset with Manifest-signed badge,
  internal-visibility defensive filter, optional upload form.
- `keel/core/templates/keel/components/quick_info.html` — right-rail
  sidebar metadata card (status / claimant / principal / timestamps +
  caller-supplied extra_fields). Matches the Yeoman canonical detail
  page Quick Info pattern.
- `tests/test_collaboration_panel.py` — 15 render tests: 6 for
  attachment_list (Manifest badge, internal-row visibility, empty state),
  3 for quick_info (rows, skip-missing, extra_fields), 6 for the
  orchestrator (all-sections render, claim-row toggle, sub-section
  opt-out, collapsed mode).

### Fixed
- `keel_site/settings.py` adds `django.contrib.humanize` to
  `INSTALLED_APPS`. Production keel templates (`comment_section.html`,
  `collaborator_list.html`, and the new Wave 1 components) have always
  used `{% load humanize %}` for `naturaltime` filters; the test settings
  never installed it, which silently made those templates untestable.
  Discovered when the Wave 1 render tests first failed. Tests for the
  defensive `is_internal` filter shipped in 0.40.2 can now actually run.

### Still deferred into a Wave 1 batch 2
- `{% collaboration_panel object %}` template tag with
  `get_collaboration_panel_spec(obj, request)` resolver contract (the
  DX-phase recommendation — replaces the 6-kwarg include API). Current
  batch ships the include-based contract; the tag wraps it once Wave 2
  validates real consumption patterns.
- `python manage.py preview_collaboration_panel` management command —
  the simplest valuable form is one that takes `--product <name> --pk <id>`
  and renders that product's actual entity. That requires Wave 2 to ship
  first so there's a real product wired against the panel.

## 0.43.0 — 2026-05-14

**Retry command for failed cross-product mention dispatches.** New
`python manage.py retry_failed_mention_deliveries` walks
`MentionDelivery` rows with `peer_status='failed'` and replays the
Beacon POST. Beacon-side `(contact_slug, source_url)` idempotency
keys keep retries safe — successes on the original attempt that
just dropped the response can't double-write the provenance row.

Intended as a daily cron after restoring Beacon connectivity, or as
an on-demand admin tool. Safe to run repeatedly: no side effects on
already-OK or already-gone rows.

### Added
- `keel.mentions.management.commands.retry_failed_mention_deliveries`
  — the new mgmt command. Flags: `--limit N` (default 100), `--dry-run`,
  `--include-gone` (also retry 410 rows; default skips them).
- 10 new tests in `tests/test_mentions_retry_command.py` pinning every
  branch of the command: unconfigured Beacon (no-op), no failed rows
  (no-op), success path (peer_status → ok), failure path (peer_error
  refreshed), 410 path (peer_status → gone), skip-ok-rows, default
  skip-gone vs `--include-gone` opt-in, dry-run sends zero requests,
  missing source note silently skipped, `--limit` caps the batch size.

## 0.42.1 — 2026-05-14

**Fix:** `MentionDelivery` CheckConstraint used the deprecated
`check=` kwarg (removed in Django 5.1). Renamed to `condition=`. The
generated migration already uses `condition=`; the model class
matched after this fix. Caught by a Railway deploy failure on
`harbor-demo` (5.1+ runtime).

## 0.42.0 — 2026-05-14

**Suite-wide `@`-mentions on internal notes.** New `keel.mentions` module
adds the picker, parser, dispatch, and a polymorphic `MentionDelivery`
idempotency ledger. Typing `@username` in any note notifies the named
DockLabs user (in-app + email via `keel.notifications`); typing
`@beacon:<contact-uuid>` best-effort POSTs to Beacon's new
`/api/v1/intake/contact-mentions/` endpoint which appends a `Note` +
`ContactMentionProvenance` row to that contact's record (one-way
provenance — the external person is not notified).

Coordinated rollout across the suite: Beacon receiver in beacon#44;
full Harbor / Bounty / Helm / Yeoman wiring on the note model in
their feat/mentions PRs; infrastructure-only registration on
Admiralty / Lookout / Manifest / Purser (they get the picker
endpoint but have no `AbstractInternalNote` subclass to consume it).

### Added
- `keel.mentions` — new Django app. Public API re-exported at the
  package root: `MentionableTextarea`, `MentionFormMixin`,
  `MentionDelivery`, `parse_mentions`, `resolve_users`,
  `resolve_contacts`. See `keel/mentions/README.md` for the 5-step
  per-product integration template.
- `AbstractInternalNote.mentions` — new `ManyToManyField` to
  `AUTH_USER_MODEL`. Inherited by every concrete subclass. Each
  consuming product runs `makemigrations` + `migrate` in the same
  PR as the keel pin bump — lockstep rollout enforced by the
  `mentions.W003` system check.
- `MentionDelivery` polymorphic model with partial `UniqueConstraint`s
  per recipient kind (`keel_user` vs `beacon_contact`) and a
  `CheckConstraint` enforcing exactly one shape per row. The
  constraints are the real idempotency primitive: re-saving a note
  never double-notifies or double-writes to Beacon.
- Three Django system checks (`mentions.W001`/`W002`/`W003`) plus a
  `python manage.py check_mentions_wiring` audit command that kill
  the four silent-no-op failure modes (forgot INSTALLED_APPS, URL
  include, widget swap, or migration).
- `keel.mentions.helm_inbox.build_inbox_items(user)` — Helm
  cross-product surface. Wraps into a product's existing
  `/api/v1/helm-feed/inbox/` so the Helm aggregator picks up unread
  user mentions. User mentions only; Beacon contacts are not Helm
  users.
- 38 new tests across 5 files (parser, beacon client, model
  constraints, view, helm_inbox).

### Security notes
- The autocomplete endpoint requires `q.length >= 2`, audit-logs
  each query, and does not return `email`. Within-org user
  enumeration is named-and-accepted as residual for v1.
- Beacon's `excerpt[:500]` is sent raw across the product boundary.
  Notes containing secrets pasted into a comment will reach Beacon's
  contact record. Consumers needing redaction must apply it before
  save.

## 0.41.2 — 2026-05-14

**Wave 0 effective close.** Helm-pioneered claim banner + workflow transitions
templates promoted into `keel/components/` as parameterized, suite-shared
partials. Helm's own templates are unchanged — Wave 4 (Helm panel adoption)
migrates Helm to consume the keel versions.

Wave 0 items (f) `preview_collaboration_panel` management command and (h)
"final Wave 0 version bump" are deferred into Wave 1: (f) has nothing to
preview until Wave 1 ships the panel orchestrator, and with (f) bundled
there's no separate Wave 0 closeout version to tag. Consumers needing
Wave 0's fixes should pin `v0.41.2` or later.

### Added
- `keel/core/templates/keel/components/claim_row.html` — parameterized
  version of Helm's `_claim_banner.html`. Accepts `active_assignment`,
  `is_archived`, `claim_action` (pre-resolved URL string from caller),
  and `entity_label` (display word — defaults to "record" so the
  component is safe without it). Renders empty when claimed / archived
  / no claim URL.
- `keel/core/templates/keel/components/workflow_transitions.html` —
  parameterized version of Helm's `_project_transition_controls.html`.
  Accepts `available_transitions` (caller filters via
  `WorkflowModelMixin.get_available_transitions` — which now forwards
  `obj=self` per 0.40.2) and `transition_action` (pre-resolved URL).
  Behaviorally identical to Helm's inline-text-input version; the
  modal-vs-inline refactor for comment-required transitions
  (Phase 2 Design finding) is queued for Wave 1.
- `tests/test_claim_row_workflow_transitions.py` — 9 render tests
  pinning the public contract: render-when-empty-state-applies,
  entity_label fallback, no-form-action-without-URL footgun, etc.

### Audited
- **`AbstractActivity.visible_to` is implemented in 9/9 products.** The
  Phase 3 Eng review's E11 finding ("activity panel renders silently
  empty on products without `visible_to` — list per-product status,
  ship stubs where missing") turned out to be unfounded: every product
  (admiralty, beacon, bounty, harbor, helm, lookout, manifest, purser,
  yeoman) already has a per-product `visible_to` override. No stubs
  needed. Audit recorded in `docs/design/collaboration-panel-2026-05.md`.

## 0.41.1 — 2026-05-14

**Wave 0 (collaboration-panel) hardening, batch 2.** Performance fix for the
activity panel + durable documentation for the suite-wide collaboration-panel
rollout. Bumped to 0.41.1 because `0.42.0` (`add2c43` — `KEEL_PRODUCT_NAME` /
`KEEL_PRODUCT_CODE` split) shipped between Wave 0 batch 1 and batch 2 on the
same day.

### Fixed
- **`AbstractActivity.render_for` no longer dereferences `target`** — the
  bundled `keel/activity/_panel.html` partial never read it, but the
  per-row GenericForeignKey lookup turned a 15-row activity panel render
  into 15 extra ContentType + model queries (N+1). Subclasses that need
  `target` in their own rendering must override `render_for` and prefetch
  `target_ct`. (Both Eng review voices flagged independently.)
- **`activity_panel` template tag adds `target_ct` to `select_related`** —
  defensive even though base `render_for` no longer returns target; keeps
  the abstraction safe for product overrides.

### Added
- `keel/docs/design/collaboration-panel-2026-05.md` — durable operating
  manual for the suite-wide collaboration-panel rollout. Discoverable by
  future engineers AND AI agents (the source plan lives in Dan's personal
  `~/.claude/plans/` directory and isn't checked into any product repo).
- `keel/CHANGELOG.md` (this file) — per the DX review finding that 8 waves
  of keel changes need release notes for consumers to know what changed.
- `tests/test_activity_render_for_no_target.py` — pins the contract: default
  `render_for` does NOT include `target`. Failure mode of the regression
  it guards against is silent (extra DB queries), so the test exists to
  catch future reverts.

## 0.40.2 — 2026-05-14

**Wave 0 (collaboration-panel) hardening, batch 1.** Two critical security
boundary fixes surfaced by the `/autoplan` Run 2 dual-voice review of the
suite-wide collaboration panel plan.

### Fixed
- **`WorkflowModelMixin.get_available_transitions` and `can_transition`
  now forward `obj=self` to the engine** (`keel/core/models.py:293,301`).
  Documented contract in `keel/CLAUDE.md` "Object-scoped roles" section
  requires forwarding; the mixin had been dropping `obj` silently, breaking
  per-record role checks for any product with object-scoped roles (Helm's
  `'lead'` against `ProjectCollaborator` is the canonical case). Result of
  the bug: workflow buttons could render to the wrong users. `transition()`
  was unaffected — it passes `self` positionally via `execute(obj, …)`.
- **`comment_section.html` adds per-row defensive `is_internal` filter**
  (`{% if not comment.is_internal or request.user.is_staff %}`). Callers
  SHOULD still pre-filter (count badge + empty state reflect input
  queryset), but the template now hides internal-flagged rows from
  non-staff users at render time as defense-in-depth. Safe default if
  `request` is missing from context (`request.user.is_staff` resolves False,
  internal rows hidden).

### Added
- `tests/test_workflow_mixin_obj_forwarding.py` — regression test pinning
  the `obj=` forwarding contract. Constructs a fake `ObjectScopedEngine`
  where `'lead'` resolves to `obj.lead is user`; verifies one user sees
  different available transitions on two model instances. Test cannot
  pass without the mixin forwarding `obj`.

### See also
- Design doc: `docs/design/collaboration-panel-2026-05.md`
- Source plan (Dan's working copy): `~/.claude/plans/can-we-do-a-melodic-hippo.md`
