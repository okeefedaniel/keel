# Suite-wide Collaboration Panel — Design Doc (2026-05-14)

**Status:** APPROVED via `/autoplan` Run 2 (dual voices, all 4 phases). Wave 0 in progress.
**Source plan:** `~/.claude/plans/can-we-do-a-melodic-hippo.md` (Dan's working copy; thinking artifact, not operating manual).
**This file:** the durable, committed-to-repo operating manual. Read this first if you're adopting the panel in a product, fixing a bug in it, or asked to retrofit a new product.

## What this is

A shared `{% collaboration_panel object %}` template tag (Wave 1 ships it) that every DockLabs product's detail page renders the same way: claim row → collaborators → discussion → workflow transitions → attachments, with a right rail of `{% activity_panel %}` + Quick Info. Uniform vocabulary, product-specific prominence.

The panel complements — does NOT replace — the upstream 2026-05-04 "Suite-Wide Hierarchical Activity Layer" design doc (`/Users/dok/.gstack/projects/CT/dok-suite-activity-design-20260504-134330.md`), which owns the **chrome-level always-visible left-rail cross-record activity feed**. This panel is the **per-record main-column collaboration surface** for the team and conversation around THIS bill/grant/FOIA. Different layers, different scopes; both ship.

## Why now

1. **Pre-launch is the only cheap window.** Once we have customers and muscle memory, every cross-product visual change becomes a coordination tax. Today there are zero external users; we can move the spine of every detail page without breaking anyone's workflow.
2. **The 2026-05-11 suite design audit** identified detail-page incoherence as the highest-impact change across the suite, and named Yeoman's invitation detail page as the canonical reference. That audit becomes a stale doc the longer 7 products diverge from it. This work converts it into committed code.
3. **The suite IS the product.** DockLabs's moat against single-product point solutions is that 9 products share identity, audit, activity, and now — collaboration shape. A buyer evaluating Admiralty vs. a standalone FOIA tool should feel "this is part of an OS" within 30 seconds of a demo.

Capability work resumes after the Wave 4 procurement-signal gate. This work is a multiplier on existing capability, not a substitute for new capability.

## What lives in keel (this repo) vs in each product

| Lives in keel | Lives per-product |
|---|---|
| `keel/core/templates/keel/components/collaboration_panel.html` (Wave 1) | `<Product>Assignment(AbstractAssignment)` concrete subclass |
| `keel/core/templates/keel/components/claim_row.html` (landed in 0.41.2) | `<Product>Collaborator(AbstractCollaborator)` concrete subclass |
| `keel/core/templates/keel/components/workflow_transitions.html` (landed in 0.41.2) | `<Product>Note(AbstractInternalNote)` concrete subclass |
| `keel/core/templates/keel/components/comment_section.html` (already exists; 0.40.2 hardened) | `<Product>Attachment(AbstractAttachment)` concrete subclass |
| `keel/core/templates/keel/components/collaborator_list.html` (already exists) | `<Product>StatusHistory(AbstractStatusHistory)` concrete subclass |
| `keel/core/templates/keel/components/attachment_list.html` (Wave 1 NEW) | `<Product>WorkflowEngine` subclass with declarative `Transition()` list |
| `keel/core/templates/keel/components/quick_info.html` (Wave 1 NEW) | `<Product>Activity(AbstractActivity)` concrete subclass with `visible_to` |
| `keel/activity/templatetags/activity_tags.py` `{% activity_panel %}` (already exists; 0.41.1 hardened) | Views that pass pre-filtered + select_related querysets to the panel |
| `keel/core/models.WorkflowModelMixin` (already exists; 0.40.2 fixed) | Detail-page template that includes the panel |
| `keel/signatures/client.send_to_manifest` + `packet_approved` signal (already exists) | URL kwargs for `claim_action`, `transition_action`, `invite_action` |

## Wave order

0. **Wave 0 — Shared contract hardening (keel-only, ~3-4 days, ~30 min done as of 2026-05-14 with `ae84574`).**
   - ✅ (a) Fix `WorkflowModelMixin.get_available_transitions` and `can_transition` to forward `obj=self` (security boundary — landed in 0.40.2).
   - ✅ (b) Defensive `is_internal` filter in `comment_section.html` (defense in depth — landed in 0.40.2).
   - ✅ (d) `activity_panel` query optimization: `select_related('actor', 'target_ct')` + drop unused `target` from `render_for` (landed in 0.41.1).
   - ✅ (g) Commit this doc + CHANGELOG (landed in 0.41.1).
   - ✅ (c) Audit `AbstractActivity.visible_to` per-product implementation status — **9/9 products implement it.** No stubs needed. The Phase 3 Eng E11 concern was unfounded — every product already has a per-product `visible_to` override at `<product>/<app>/activity_models.py`. Per-product implementations: admiralty/foia (FOIA officer + watchers), beacon/interactions (zone-aware), bounty/opportunities (tracked_by + collaborators), harbor/applications (applicant + reviewer + assignment), helm/tasks (project ACL + visibility tier), lookout/tracking (tracked_by + collaborators), manifest/signatures (initiator + signers), purser (submitted_by + reviewed_by + program M2M), yeoman (agency + per-row assigned/delegated/created).
   - ✅ (e) Promote + parameterize Helm's `_claim_banner.html` and `_project_transition_controls.html` to keel components — landed in 0.41.2 as `keel/components/claim_row.html` and `keel/components/workflow_transitions.html`. Helm's own templates are unchanged; Wave 4 (Helm panel adoption) migrates Helm to consume the keel versions. 9 render tests pin the contract.
   - 🔁 (f) `python manage.py preview_collaboration_panel` management command — **deferred into Wave 1**. The command's purpose is to render the panel against a fake entity for 5-minute inner-loop verification, but the panel orchestrator (`collaboration_panel.html`) doesn't exist yet — Wave 1 ships it. Building a preview command for a non-existent component is busy work; bundle (f) with Wave 1 so the command can preview the real thing.
   - 🔁 (h) Final keel bump for Wave 0 — **deferred into Wave 1**. With (f) bundled into Wave 1, there's no separate "Wave 0 closeout" version to tag. The next keel bump happens when Wave 1 ships the component + preview command together.

**Wave 0 effective close: 0.41.2 (1cedc76).** 6 of 8 named items landed; the remaining 2 are bundled into Wave 1 because they depend on Wave 1's output. Anyone consuming keel for Wave 0 fixes should pin `v0.41.2` or later.

1. **Wave 1 — Build the shared component in keel.** `keel/components/collaboration_panel.html` orchestrator + render-test against a fake `TestEntity`. No product changes yet.

2. **Wave 2 — Yeoman adoption + abstraction-test gate.** Add `InvitationCollaborator(AbstractCollaborator)`, migrate `InvitationAttachment → AbstractAttachment`, add `InvitationAssignment(AbstractAssignment)`. At Wave 2's end, evaluate the component honestly: (a) is the per-product diff smaller than per-template enforcement would have produced? (b) does the component require zero product-specific config flags? (c) does the visual outcome match the canonical Yeoman layout without overrides? If YES → continue. If NO → fall back to per-product `/design-review` enforcement for Waves 3-7.

3. **Wave 3 — Admiralty (UC-1 re-sequence from Wave 7).** Hardest retrofit AND gravitas product for state procurement. Three new abstracts. FOIA stepper + statutory clock as primary leading content (panel collapsed-by-default). If FOIA's constraints break the panel contract, find out in week 4 instead of week 9.

4. **Wave 4 — Helm + 🛑 PROCUREMENT-SIGNAL KILL-SWITCH (UC-2).** Add declarative `Transition()` list to `ProjectWorkflowEngine`. Adopt the panel. **STOP at the end of Wave 4.** Evaluate: has any procurement conversation indicated suite coherence is a deal-driver? If YES → continue Waves 5-8. If NO → halt and pivot back to capability/compliance/sales blockers.

5. **Wave 5 — Bounty + Lookout in parallel** (gated on Wave 4 procurement signal).
6. **Wave 6 — Harbor** (gated).
7. **Wave 7 — Beacon** (gated + cross-coupled on upstream `keel.activity` `Follow`/`ActivityLog` migration completing).
8. **Wave 8 — Purser** (gated; net-new product work, not retrofit).

## The four User Challenges accepted

UC-1: Admiralty moved from Wave 7 to Wave 3 (both Eng + CEO voices agreed).
UC-2: Wave 4 procurement-signal kill-switch (both voices agreed).
UC-3: Wave 2 fallback gate — if abstraction is awkward, fall back to per-product `/design-review` for Waves 3-7.
UC-4: Wave 0 contract hardening (both Eng + DX voices agreed independently).

## Critical keel defects fixed in Wave 0 so far

| Defect | File | Severity | Status |
|---|---|---|---|
| `WorkflowModelMixin` drops `obj=self` when calling engine — silently bypasses object-scoped role checks for any product with per-record roles like Helm's `'lead'` | `keel/core/models.py:293,301` | Critical (security boundary) | Fixed in 0.40.2 (`ae84574`) |
| `comment_section.html` renders every comment in input queryset — no defensive `is_internal` filter; relies entirely on caller-side filtering | `keel/core/templates/keel/components/comment_section.html` | Critical (data leak) | Fixed in 0.40.2 (`ae84574`) |
| `AbstractActivity.render_for` dereferences `self.target` per-row — N+1 on every activity panel render even though the bundled template never reads `target` | `keel/activity/models.py:236` | High (performance) | Fixed in 0.41.1 |

## Open Wave 0 work (next session)

- (c) `visible_to` audit per product — keel ships the abstract; each product MUST subclass and implement. Audit which products have it today; ship stubs where missing.
- (e) Promote + parameterize Helm templates — replace `{% url 'tasks:claim_project' project.slug %}` style hardcoding with `{% url claim_action %}` kwarg-driven URLs.
- (f) `python manage.py preview_collaboration_panel` management command — 5-minute inner-loop verification with a documented per-product invocation.
- (h) Final Wave 0 version bump.

## How an AI agent should pick this up

1. Read this file end-to-end.
2. Read the source plan at `~/.claude/plans/can-we-do-a-melodic-hippo.md` for the full review history, dual-voice findings, and audit trail.
3. Read `keel/CLAUDE.md` for engineering principles, especially "Project Lifecycle Standard", "Object-scoped roles", and "Keel version bumping — the pip cache trap".
4. Check the CHANGELOG to see which Wave 0 items have landed.
5. Pick the next unfinished Wave 0 item.

## References

- Source plan (Dan's working copy): `~/.claude/plans/can-we-do-a-melodic-hippo.md`
- Upstream activity-layer design doc: `~/.gstack/projects/CT/dok-suite-activity-design-20260504-134330.md`
- Suite engineering principles: `keel/CLAUDE.md`
- Canonical detail page reference: `yeoman/yeoman/templates/yeoman/invitation_detail.html`
- Reference workflow implementation: `harbor/applications/workflows.py`
