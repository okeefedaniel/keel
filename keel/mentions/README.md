# keel.mentions

Suite-wide `@`-mentions on internal notes. Ships in keel 0.39.0.

When a user types `@username` in a note's content, the named DockLabs
user gets an in-app + email notification. When a user types
`@beacon:contact-slug`, an internal note is appended to that contact's
record on Beacon (one-way provenance — the external person is not
notified). Both writes share an idempotency ledger (`MentionDelivery`)
so re-saving a note never double-delivers.

## 60-second quickstart (Harbor reference)

```python
# 1. INSTALLED_APPS in settings.py
INSTALLED_APPS = [
    # ...
    'keel.mentions',
]

# 2. URL include in urls.py
urlpatterns = [
    # ...
    path('keel/mentions/', include('keel.mentions.urls')),
]

# 3. Form mixin + widget on your comment form
from keel.mentions import MentionFormMixin, MentionableTextarea

class ApplicationCommentForm(MentionFormMixin, forms.ModelForm):
    class Meta:
        model = ApplicationComment
        fields = ['content', 'is_internal']
        widgets = {'content': MentionableTextarea()}

    # Required: how to derive the parent record for source_url + source_label
    def get_mention_source(self):
        return self.instance.application
```

```bash
# 4. Generate + apply the migration for your concrete note subclass
python manage.py makemigrations applications
python manage.py migrate

# 5. (recommended) Add prefetch_related on list views rendering notes
#    e.g., in ApplicationDetailView:
#    queryset = ApplicationComment.objects.prefetch_related('mentions')
```

```bash
# 6. Verify wiring
python manage.py check_mentions_wiring
```

That's it. Type `@` in a comment box, see the picker, save the comment,
the recipient gets notified.

## Beacon contact mentions (cross-product)

Mentions of Beacon contacts (`@beacon:sarah-jones`) appear in the
picker ONLY when Beacon is configured for this product:

```python
# settings.py — both required
BEACON_INTAKE_URL = 'https://beacon.docklabs.ai/'
BEACON_INTAKE_API_KEY = 'env-injected'
```

When configured, the picker queries Beacon's
`/api/v1/contacts/lookup/?q=...` endpoint. Selecting a contact inserts
`@beacon:<slug>` into the textarea. On save, `keel.mentions` POSTs to
Beacon's `/api/v1/intake/contact-mentions/` which appends a
`ContactNote` row to that contact's record (and a
`ContactMentionProvenance` row for the contact-detail "Mentioned in…"
panel — v1.5).

**Best-effort cross-product call.** If Beacon is unreachable, the
note save still succeeds — the local `MentionDelivery` row is written
with `peer_status='failed'` and `peer_error=<reason>`. A retry job
(forthcoming `manage.py retry_failed_mention_deliveries`) re-attempts
on a later schedule. Beacon-side idempotency keys on
`(contact_slug, source_url)` so retries never double-write.

When `BEACON_INTAKE_URL` is unset, the picker shows zero contacts and
no cross-product call is ever made. Standalone deployability holds.

## Multi-subclass products

If your product has more than one concrete `AbstractInternalNote`
subclass (e.g., `ApplicationComment` and a separate `StaffNote`),
`makemigrations` generates one through-table migration **per
subclass**. Both must ship in the same PR as the keel pin bump.

```bash
python manage.py makemigrations --dry-run --check
# Asserts no missing migrations. Use in CI to catch a forgotten one.
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Type `@`, nothing happens | `keel.mentions` not in `INSTALLED_APPS` | Add it; restart |
| Type `@`, JS console shows 404 on `/keel/mentions/search/` | URL include missing | Add `path('keel/mentions/', include('keel.mentions.urls'))` |
| Picker opens, comment save crashes with `relation "..._mentions" does not exist` | M2M migration not run | `python manage.py makemigrations <app> && migrate` |
| Comment saves but no notification | Widget on form is wrong class | `widgets = {'content': MentionableTextarea()}` |
| `@beacon:slug` in note text but no Beacon note appears | Beacon unreachable or unconfigured | Check `BEACON_INTAKE_URL`; inspect `MentionDelivery.peer_status` |
| List page slow with many notes | Missing `prefetch_related('mentions')` | Add it to the queryset |

When in doubt: `python manage.py check_mentions_wiring`.

## Overrides (settings)

All optional. Defaults are opinionated; override only when needed.

| Setting | Default | Purpose |
|---|---|---|
| `KEEL_MENTIONS_RECIPIENT_CAP` | `25` | Max mentions dispatched per save (users + contacts combined) |
| `KEEL_PRODUCT_CODE` | (read by keel.notifications too) | Lowercase product code used for org/role scoping |
| `BEACON_INTAKE_URL` | `''` | Beacon base URL; unset → contacts disabled |
| `BEACON_INTAKE_API_KEY` | `''` | Bearer token for Beacon intake |

Per-product email template override: if `keel/mentions/emails/{KEEL_PRODUCT_CODE}/note_mentioned.html` exists in your template loader path, it is used instead of the default. Useful for product-specific branding.

## Rollback

Mentions data is preserved by design — the `mentions` M2M and
`MentionDelivery` rows are an audit trail of who mentioned whom and
when (FOIA-relevant correspondence). Rollback is forward-only: you can
roll back the keel pin, but do NOT `migrate <app> zero` on the M2M
through-tables. The orphaned tables are harmless and preserve the
audit trail for any future re-roll-forward.

## What's where

| File | Purpose |
|---|---|
| `parser.py` | Two-form regex + token dedupe + code-block exclusion |
| `models.py` | Polymorphic `MentionDelivery` (KeelUser OR Beacon contact) |
| `notify.py` | `dispatch_mentions()` — the get-or-create + notify/POST orchestrator |
| `beacon.py` | Best-effort cross-product Beacon client |
| `forms.py` | `MentionFormMixin._save_m2m` hook |
| `widgets.py` | `MentionableTextarea` with autocomplete data attr |
| `views.py` | `mentions_search` JSON endpoint for the picker |
| `helm_inbox.py` | `build_inbox_items()` for Helm cross-product surface |
| `checks.py` | Three system checks (W001/W002/W003) |
| `management/commands/check_mentions_wiring.py` | One-shot integration audit |
| `static/keel/mentions/mentions.js` | Vanilla-JS picker (state machine, ARIA combobox) |
| `static/keel/mentions/mentions.css` | Picker styles (docklabs-v2.css tokens) |
| `templates/keel/mentions/emails/note_mentioned.{html,txt}` | Email templates |

See `keel/CLAUDE.md` § "Collaboration & Notes → @-mentions" for the
suite-level integration tenets.
