- **Shared calendar components in `docklabs-v2.css`** — `.cal-head`, `.cal-toolbar`,
  `.cal-surface`, `.cal-ev` and its state modifiers, `.cal-legend`, `.cal-sync`,
  plus the interaction states (`.cal-ghost`, `.cal-conflict`, `.cal-notice`). They
  live in keel rather than a product so the second `keel.calendar` adopter does not
  redraw the event chip.

  The chip carries four dimensions in a ~125px cell: type via left-edge **style**,
  status via left-edge **color**, origin via a trailing **glyph**, ownership via
  **weight**. Color rides a 3px rule instead of filling the chip — a filled chip
  breaks the suite status-dot rule and makes every row shout, so the one that needs
  action stops standing out. Exactly one filled pill is permitted, for exception
  states.

  Includes the overrides that neutralise FullCalendar's own event chrome. Without
  them its default blue fill and white text paint straight over any custom
  `eventContent`, which is not obvious from the DOM and costs a debugging round to
  find.

  Below 767px the month grid is dropped rather than squeezed: seven columns on a
  phone gives roughly 50px per day. The agenda list is the mobile design, with 44px
  touch targets.
