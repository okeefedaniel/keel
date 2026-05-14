# Keel Changelog

Notable changes per release. Newest first. Per the pip-cache-trap rule in
`keel/CLAUDE.md`, every meaningful change MUST bump `keel/__init__.py`
`__version__` AND `pyproject.toml` `version` in the same commit.

## 0.41.1 — 2026-05-14

**Wave 0 (collaboration-panel) hardening, batch 2.** Performance fix for the
activity panel + durable documentation for the suite-wide collaboration-panel
rollout. Bumped to 0.41.1 because `0.41.0` (`add2c43` — `KEEL_PRODUCT_NAME` /
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
