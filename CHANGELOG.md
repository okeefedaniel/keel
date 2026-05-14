# Keel Changelog

Notable changes per release. Newest first. Per the pip-cache-trap rule in
`keel/CLAUDE.md`, every meaningful change MUST bump `keel/__init__.py`
`__version__` AND `pyproject.toml` `version` in the same commit.

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
