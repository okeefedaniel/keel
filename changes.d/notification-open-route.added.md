- **`keel_notifications:open`** (`/<pk>/open/`) — marks a notification read and
  forwards to its target. A notification with a blank `link` falls back to the
  inbox. Note this is a GET that mutates state (it marks the row read), which is
  deliberate: the alternative reintroduces the JavaScript dependency whose
  failure caused the bug above. `read_at` is therefore evidence of delivery, not
  proof of attention — a prefetching browser can set it slightly early.
