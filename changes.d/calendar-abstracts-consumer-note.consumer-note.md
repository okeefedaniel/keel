- **Products with a concrete `CalendarEvent` need a migration for this release.**
  `AbstractCalendarEvent` gained five fields and `event_type` gained a default, so
  every subclass changes shape. Today that is **yeoman** (`core.CalendarEvent`) and
  **beacon** (`core.CalendarEvent` — beacon does not use the calendar feature but
  does subclass the abstract). Ship the per-product migration in the same wave as
  the keel bump, or the next deploy fails that product's
  `makemigrations --check --dry-run` gate. All additions are nullable or defaulted,
  so the migration is a no-op at runtime.
