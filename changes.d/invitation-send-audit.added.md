- **`Invitation.email_sent_at` / `email_cc` / `email_error`** record whether
  the invitation email actually reached the mail backend, when, whether a
  copy was CC'd, and any send error — so "did the invite go out?" is
  answerable from the row (and the admin invitation list) without
  cross-referencing the Resend dashboard. `send_invitation` stamps them on
  every row in the batch. Migration `keel_accounts.0023`.
- **The "CC me" checkbox now defaults to checked** on the invitation form so
  a beta copy isn't silently dropped when the form re-renders after a send.
