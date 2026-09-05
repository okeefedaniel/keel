- **BREAKING: `AbstractCalendarEvent.status` is renamed to `sync_status`**, and the
  inner `Status` choices class to `SyncStatus`. The field always meant "has this
  reached the provider yet", but sitting beside the new `hold_status` (the domain
  state a human reads) it looked like one concept spelled two ways. Both names are
  now self-describing.

  The rename is deliberate rather than adding an alias: a stale `event.status`
  reference now raises instead of silently comparing a provider-delivery value
  against hold vocabulary. Nothing in keel or any product referenced the inner
  `Status` class, and the only in-tree readers were `keel.calendar.service` and
  Yeoman's admin, both updated.
