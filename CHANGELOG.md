# Changelog

All notable changes to keel are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.39.0] - 2026-05-13

### Added

- **Suite-wide @-mentions on notes (`keel.mentions`).** New module providing the
  picker widget, parser, dispatch, and a polymorphic `MentionDelivery` ledger.
  Typing `@username` in a comment notifies the named DockLabs user via the
  existing `keel.notifications` pipeline (in-app + email, user-mutable via the
  preferences UI). Typing `@beacon:contact-slug` appends a `ContactNote` to that
  contact's record on Beacon via best-effort cross-product POST — provenance,
  not communication. See `keel/mentions/README.md` for the 5-step integration
  per product.
- `mentions` M2M on `AbstractInternalNote`. Inherited by every concrete note
  subclass. Each consuming product must run `makemigrations` + `migrate` on its
  note app(s) in the same PR as the keel pin bump — lockstep rollout enforced
  by CI gate and the new `mentions.W003` system check.
- `MentionDelivery` model with partial `UniqueConstraint`s per recipient kind
  (`keel_user` vs `beacon_contact`) and a `CheckConstraint` enforcing exactly
  one shape per row. The unique constraints are the real idempotency primitive:
  re-saving a note never double-notifies or double-writes to Beacon.
- Three Django system checks — `mentions.W001` (URL include missing),
  `mentions.W002` (form mixin wired but wrong widget), `mentions.W003`
  (concrete `AbstractInternalNote` subclass missing the M2M migration).
- `python manage.py check_mentions_wiring` one-shot audit command. First thing
  to run when "mentions don't work in my product."
- `keel.mentions.helm_inbox.build_inbox_items(user)` — Helm cross-product inbox
  surface. Wraps into a product's existing `/api/v1/helm-feed/inbox/` endpoint
  to surface recent unread mentions in Helm's "Awaiting Me" column. User
  mentions only — Beacon contacts aren't Helm users.
- `keel/mentions/README.md` integration guide — 60-second quickstart,
  multi-subclass migration, troubleshooting table, override recipes,
  forward-only rollback framing.
- 38 new tests in `tests/test_mentions_*.py` covering the parser (two-form
  regex with code-block exclusion and dedupe), the Beacon client (every
  failure mode returns gracefully without raising), the polymorphic
  `MentionDelivery` constraints, the `mentions_search` view shape and auth,
  and the Helm inbox filtering.

### Changed

- `keel.core.AbstractInternalNote` carries a new `mentions` M2M field. The
  field has `blank=True` and is harmless when `keel.mentions` is not
  installed in INSTALLED_APPS — but the inherited field DOES require a
  per-product migration on every concrete subclass. Bumping to 0.39.0
  without that migration will 500 on the next comment save.
- CLAUDE.md gains an `## @-mentions on notes` subsection under
  Collaboration & Notes documenting the integration tenets, the lockstep
  rollout rule, and the rollback-is-forward-only contract.

### Security notes

- The autocomplete endpoint requires `q.length >= 2`, audit-logs each
  query, and does not return `email` — within-org user enumeration is
  named-and-accepted as residual risk for v1.
- Beacon's `excerpt[:500]` is sent raw across the product boundary. Notes
  containing secrets pasted into a comment will reach Beacon's contact
  record. Consumers needing redaction must apply it before save.

