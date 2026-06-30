# Keel — Development Guidelines

## Maintaining the Engineering Principles

The canonical cross-product standards live in **`docklabs_principles.md`** (in project memory). All principles apply to Keel and every product built on it.

**Before editing any file**, check whether the change touches an area covered by the principles. **When a change establishes a new cross-product pattern or decision**, update `docklabs_principles.md` — it is the single source of truth that all DockLabs projects share. Do not let it go stale.

## Key Keel-Specific Rules

### FOIA Is a Core Tenet

Any agency-submitted content — including communications, notes, documents, financial records, schedules, applications, testimony — **must** be exportable to Admiralty via the FOIA export system. Communications (emails, messages, letters, public comments, correspondence) are the highest-priority FOIA category and must always be registered.

When adding a new model or feature that stores agency content:
1. Register it with `foia_export_registry.register()` in `AppConfig.ready()`
2. Inherit from `KeelBaseModel` (captures `created_at`, `updated_at`, `created_by`)
3. Add `{% foia_export_button %}` to detail templates via `FOIAExportMixin`
4. Ensure `AuditMiddleware` is in the stack for IP capture
5. Validate with `python manage.py foia_audit`

### Abstract-First Design

Keel provides abstract base models. Products subclass and make them concrete. Never add product-specific logic to Keel's abstract models — extend them in the product instead.

### Immutable Audit Trails

`AbstractAuditLog` and `AbstractStatusHistory` are append-only. They raise on delete/update. Never bypass this.
