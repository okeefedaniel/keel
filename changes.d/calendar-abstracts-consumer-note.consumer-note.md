- **Products with a concrete `CalendarEvent` need a HAND-WRITTEN migration for this
  release.** `AbstractCalendarEvent` gained five fields, `event_type` gained a
  default, and **`status` was renamed to `sync_status`**. Affected today: **yeoman**
  (`core.CalendarEvent`) and **beacon** (`core.CalendarEvent` — beacon does not use
  the calendar feature but does subclass the abstract).

  **`makemigrations` will not detect the rename, and never prompts for it.** The
  autodetector compares a removed field against added ones using the full
  `deconstruct()` signature, and `sync_status` carries a `help_text` the old
  `status` did not — so it reads as two unrelated fields and emits `AddField` +
  `RemoveField`, which **drops the column and its data**. This is true with or
  without `--noinput`; there is no interactive answer that fixes it.

  Write the operation explicitly instead, ordered before the index work:

      migrations.RenameField('calendarevent', 'status', 'sync_status'),
      migrations.AlterField('calendarevent', 'sync_status', ...),

  Everything else in the migration is additive or defaulted and is a runtime
  no-op. Also update any admin referencing `status` — Django's system checks
  (admin.E035 / E108 / E116) will refuse to start until you do, which is the
  rename failing loudly by design.

  Ship it in the same wave as the keel bump, or the next deploy fails that
  product's `makemigrations --check --dry-run` gate.
