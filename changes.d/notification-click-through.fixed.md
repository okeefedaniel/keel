- **Notification inbox rows are clickable again (suite-wide).** The row anchor
  carried both `href` and `hx-post`, and htmx cancels the default action of any
  anchor it handles (`shouldCancel()` returns true for an `<a href>` whose href
  isn't a bare fragment). Every click fired the mark-read POST and called
  `preventDefault()`, so clicking a notification silently went nowhere. Rows now
  link at the new `keel_notifications:open` route, which marks the row read
  server-side and 302s to `notification.link`. Works without JS; the separate
  "mark as read" check button is unchanged.
