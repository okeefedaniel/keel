- **`AbstractCalendarEvent` gains five fields** so a row can represent a calendar
  hold, not only a synced event: `hold_status` (tentative / confirmed / cancelled),
  `provider_uid` (client-generated idempotency key, so a retry or double-submit
  converges on one provider event instead of two), `external_etag` +
  `external_updated_at` (external-wins comparison), `revision` (bumped per local
  edit and checked on save, rejecting a stale tab rather than silently
  overwriting), and `attendees`.
- **`event_type` now defaults to `'calendar_hold'`** — it was a required registry
  key, which a free-standing hold does not have.
