- **`AbstractCalendarConnection`** — a user's OAuth connection to one calendar
  provider. Access and refresh tokens are `EncryptedTextField` (a refresh token is
  a long-lived read/write key to a real person's calendar and never sits in the
  database as plain text). Carries the delta `sync_token`, a `last_sync_at`
  (attempt) and a separate `last_successful_sync_at` — the staleness canary that
  distinguishes a healthy sync from a green cron running over one that silently
  stopped. One active connection per user per provider.
- **`AbstractCalendarDelegation`** — a standing grant letting one user act on
  another's calendar, at `view_free_busy` / `view_details` / `edit`. This is a
  **security boundary, not sharing UX**: a delegate's write authenticates as the
  GRANTOR using the grantor's own token, so the provider performs no check of its
  own and this row is the only gate. Uniqueness is a **partial** constraint on
  active grants (`revoked_at IS NULL`), not `unique_together`, so revocations stay
  auditable. `view_free_busy` is required to SHAPE the response, not merely gate
  it — returning title, location, attendees or external ids at that level is a
  privacy leak.
