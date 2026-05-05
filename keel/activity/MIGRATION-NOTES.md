# keel.activity — Migration Notes

**Phase 1A Week 1 Day 1 spike output.** Read this before scaffolding any code under `keel/activity/`.

The eng plan at `/Users/dok/.gstack/projects/CT/eng-plan-phase-1a.md` made assumptions about how `keel.core` audit works. The spike found those assumptions wrong in load-bearing places. This file documents what's actually there and how the activity layer maps onto it.

## Spike scope

Verify before Week 3 (Manifest peer wiring) that the audit middleware writes the JSON shape the eng plan's Manifest promotion rules assumed. Specifically: do audit rows for SigningStep status transitions carry `changes['status']['from']` / `['to']` fields?

## What's actually there

### Three-layer audit pipeline

```
keel.core.middleware.AuditMiddleware            (sets thread-local user/IP, logs login events)
              ↓
keel.core.audit_signals                          (post_save / post_delete signals → log_audit())
              ↓ (only for models registered via register_audited_model)
keel.core.audit.log_audit()                      (canonical write: AuditLog.objects.create(...))
```

### AuditMiddleware does NOT auto-audit model saves

`AuditMiddleware.__call__` only:
1. Sets `request.audit_ip` from `X-Forwarded-For` or `REMOTE_ADDR`
2. Stores `(user, ip)` in thread-local via `set_audit_context(...)`
3. Wraps the view in try/finally to clear thread-local context on exit

The `user_logged_in` signal handler is the ONLY place AuditMiddleware writes audit rows directly — for login events, with a fixed shape: `action='login'`, `entity_type='User'`, `changes={}`.

### `keel.core.audit_signals` is the auto-audit pipeline (opt-in registry)

Products call `register_audited_model('app.Model', 'Display Name')` in their AppConfig.ready(). The signal handlers `_on_save` / `_on_delete` then fire on every save/delete of those registered models and call `log_audit()`.

**Verified usage:** Manifest registers 9 signature-related models in `manifest/signatures/apps.py`:
```python
register_audited_model('signatures.SignatureFlow', 'Signature Flow')
register_audited_model('signatures.SigningPacket', 'Signing Packet')
register_audited_model('signatures.SigningStep', 'Signing Step')
# ... 6 more
```

### `changes` field is a SNAPSHOT, not a diff

`audit_signals._compute_changes(instance, skip_fields)`:

```python
for f in instance._meta.concrete_fields:
    if f.name in skip_fields:
        continue
    if f.is_relation:
        val = getattr(instance, f'{f.name}_id', None)
        if val is not None:
            changes[f.name] = str(val)
    else:
        val = getattr(instance, f.name, None)
        if val is not None and val != '' and val != [] and val != {}:
            changes[f.name] = str(val)[:500]
```

**Captures the current value of every non-skipped field as a string.** No old-value tracking. No from→to diff. For a SigningStep status transition (`PENDING → SIGNED`), the audit row's `changes` looks like:

```json
{
  "status": "SIGNED",
  "signed_at": "2026-05-04 12:34:56+00:00",
  "signed_ip": "203.0.113.1",
  "signer_email": "alice@agency.gov",
  "step_index": "2",
  "packet_id": "f3a9b...",
  "..."
}
```

You can see what is now true. You cannot see what changed.

### `action` is `'create'` or `'update'` for auto-signal saves

`_on_save` sets `action = 'create' if created else 'update'`. The richer enum values (`STATUS_CHANGE`, `APPROVE`, `SUBMIT`, etc.) only land in audit rows when product code explicitly calls `log_audit(action='status_change', ...)`. Manifest's `services.py` does NOT make explicit `log_audit` calls — verified via `grep -rn "log_audit" manifest/signatures/services.py` returning zero results.

### AbstractAuditLog uses string identity, not ContentType GFK

```python
class AbstractAuditLog(models.Model):
    user        = FK(settings.AUTH_USER_MODEL, on_delete=SET_NULL, null=True)
    action      = CharField(max_length=25, choices=Action.choices)
    entity_type = CharField(max_length=100)    # e.g. 'Signing Step' (display name from registry)
    entity_id   = CharField(max_length=255)    # str(instance.pk)
    description = TextField(blank=True)
    changes     = JSONField(default=dict)
    ip_address  = GenericIPAddressField(null=True)
    timestamp   = DateTimeField(auto_now_add=True)
```

**No `content_type` ForeignKey.** The eng plan's promotion-registry lookup keyed on `(audit.content_type.app_label, audit.content_type.model, audit.action)` does not match reality.

## Implications for the activity layer design

The eng plan's promotion-registry-from-audit-row model breaks for any verb that needs structured from/to information. Two failure modes:

1. **Manifest's `signing.signed` / `signing.declined` / `signing.next_signer_active`:** the audit row from a SigningStep save doesn't carry the `from_status` for the transition. Inferring "this update was a sign event" from the snapshot is fragile (what if a different field changed?).
2. **`workflow.transitioned`:** same shape. The status history row has from/to; the audit row doesn't.

## Revised activity-layer architecture (replaces eng plan §4)

**Two tracks, not one:**

### Track A — Auto-promotion via registry

For simple "model X saved → activity row" cases where the audit-row creation IS the activity event. Examples:

- `entity_type='Project Collaborator'`, `action='create'` → `collab.added` activity
- `entity_type='Project Collaborator'`, `action='delete'` → `collab.removed` activity
- `entity_type='Interaction'`, `action='create'` → `interaction.logged` activity (Beacon)
- `entity_type='Interaction Attachment'`, `action='create'` → `interaction.attachment_added` activity

The promotion registry is keyed on `(entity_type, action)` (NOT `app_label.model + action`). The rule's `target_fn(audit)` does its own model lookup using `audit.entity_id`:

```python
@activity_promotion(
    entity_type='Project Collaborator',
    action='create',
    verb='collab.added',
    target_fn=lambda audit: ProjectCollaborator.objects.get(pk=audit.entity_id).project,
    action_fn=lambda audit: ProjectCollaborator.objects.get(pk=audit.entity_id),
    source_label_fn=lambda audit: f'{audit.user} added a collaborator',
)
```

Lookup at promotion time: `PromotionRegistry.lookup(entity_type='Project Collaborator', action='create')`. Same hierarchical model as before; the key shape changed.

### Track B — Explicit `record_activity()` calls in service code

For domain-rich verbs where the audit row alone doesn't capture the structured meaning. The product service that performs the transition calls `record_activity()` directly with explicit metadata:

```python
# manifest/signatures/services.py — sign_step()

def sign_step(step: SigningStep, signer: KeelUser):
    old_status = step.status
    step.status = SigningStep.Status.SIGNED
    step.signed_at = timezone.now()
    step.signed_ip = get_client_ip()
    step.save()  # ← audit row fires automatically (Track A captures CREATE not UPDATE; this UPDATE flows through but no rule registered on Signing Step UPDATE)
    
    # ← record_activity fires explicitly with structured from/to
    from keel.activity.services import record_activity
    record_activity(
        actor=signer,
        verb='signing.signed',
        target=step.packet,
        action=step,
        metadata={
            'from_status': old_status,
            'to_status': step.status,
            'step_index': step.step_index,
            'signer_email': step.signer_email,
        },
    )
    
    # If this transition activated the next signer, fire that verb too
    next_step = step.packet.next_pending_step()
    if next_step:
        record_activity(
            actor=None,  # system event
            verb='signing.next_signer_active',
            target=step.packet,
            action=next_step,
            metadata={'step_index': next_step.step_index, 'signer_email': next_step.signer_email},
        )
```

**`record_activity()` writes BOTH AuditLog (with `action='status_change'`) AND Activity in one transaction**, with `_skip_promotion=True` so the auto-signal pathway doesn't double-create. The product's auto-signal audit row for the underlying SigningStep.save() still fires (with `action='update'`) but no promotion rule matches it, so no duplicate activity is produced.

### When to use which track

| Pattern | Track |
|---|---|
| New row created → activity row should fire | A (registry) |
| Row deleted → activity row should fire | A (registry) |
| Row updated AND the update has structured semantic meaning (from/to status, sign event, etc.) | B (explicit) |
| Row updated AND no specific verb needed | neither — audit captures it, activity skips |
| Domain event with no underlying model save (e.g., webhook received, batch import completed) | B (explicit) — `record_activity()` writes both AuditLog and Activity |

## Other findings worth noting

### `_DEFAULT_SKIP_FIELDS` defaults

`audit_signals.py` skips `{'updated_at', 'created_at', 'search_vector', 'password', 'last_login'}` from every audit row. Activity-layer notes:
- `created_at` skip means Activity rows can't read original creation time from `audit.changes`. Fine — Activity has its own `created_at`.
- `password` skip is the right security default.

### Audit log uses `string` IDs everywhere

`entity_id = CharField(max_length=255)`. Promotion rules' `target_fn` must convert: `Model.objects.get(pk=audit.entity_id)`. UUIDs work directly; integer PKs require a `.get(pk=int(audit.entity_id))` cast. Plan accordingly.

### `entity_type` is the registered display name, not the model class name

`register_audited_model('signatures.SigningStep', 'Signing Step')` produces audit rows with `entity_type='Signing Step'` (with a space). Promotion registry keys must match the display name exactly. Document this in the registry registration so a typo doesn't silently fail to match.

### Audit log is per-product (not per-app)

Each product subclasses `AbstractAuditLog` once. `KEEL_AUDIT_LOG_MODEL` setting points at it (e.g., `'core.AuditLog'` for most products, `'signatures.AuditLog'` for Manifest standalone). All audit rows from all apps in that product land in the one table.

### `keel.core.audit_signals.connect_audit_signals()` connects signals at app-ready time

Called from `KeelCoreConfig.ready()` after products have finished registering models. The activity layer's signal handlers should connect at the same point in the lifecycle (`keel.activity.apps.AppConfig.ready()`).

## Updates needed in eng-plan-phase-1a.md

1. **§4 Promotion registry:** key shape changes from `(app_label, model, action)` → `(entity_type, action)`. `target_fn` does its own model lookup via `audit.entity_id`.
2. **§3 Signal wiring:** `on_audit_saved` reads `instance.entity_type` not `instance.content_type.app_label + instance.content_type.model`.
3. **New §4.5 Track B (explicit `record_activity()` calls):** new section documenting when service code makes explicit calls vs. relying on the registry. Manifest's signing.* verbs ALL use Track B.
4. **§14 Week 3 (Manifest peer):** rewrite `_register_manifest_promotions()` example. Remove the status-diff inference. Replace with: register Track-A promotions for SigningStep `create` (if needed) and document that signing transitions use Track B in `manifest/signatures/services.py`.
5. **§13 Open Question 3 (audit shape):** RESOLVED. Document the shape: snapshot not diff; entity_type/entity_id strings not GFK.
6. **AbstractAuditLog `metadata` field addition:** still needed — `record_activity()` system events don't have a diff and shouldn't pollute `changes` with a snapshot they don't have. The `metadata` field is the right home for structured context.

## What did NOT need to change

- The hierarchical audit → activity → notification topology
- AbstractActivity model design (target/action GFK, 5-tier visibility, audit_ref FK, metadata)
- AbstractWatcher model design
- Subscriber resolution + dedup in dispatch
- Signal-cycle prevention via `KEEL_AUDIT_EXCLUDED_MODELS`
- The `_skip_promotion` ContextVar guard (still works the same way)
- Signed user_token cross-product auth design
- The 5-tier visibility (incl. `stub` for Beacon)
- 5-week Phase 1A cadence (Week 1 spike landed cleanly inside Day 1)

## Status

✅ Spike complete. AuditMiddleware shape verified. Eng plan §3, §4 need targeted updates. Models can scaffold against the corrected shape.

Next step: update eng plan, then scaffold `keel/activity/__init__.py`, `apps.py`, `models.py` against the corrected promotion-registry shape.
