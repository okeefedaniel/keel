"""Guards for the shared calendar components in docklabs-v2.css.

The suite has a history of CSS regressions that ship silently — a stale wheel
serving pre-fix CSS, an `opacity: 0` animation that never fires, a `flex: 1`
collapsing a column to zero width. These pin the load-bearing rules so a
reformat or a merge cannot quietly undo them.
"""
from pathlib import Path

import pytest

CSS = (
    Path(__file__).resolve().parent.parent
    / 'keel' / 'core' / 'static' / 'css' / 'docklabs-v2.css'
).read_text()


def test_calendar_components_are_present():
    for cls in ['.cal-head', '.cal-toolbar', '.cal-surface', '.cal-ev',
                '.cal-legend', '.cal-sync', '.cal-views']:
        assert cls in CSS, f'{cls} missing from the design system'


def test_fullcalendar_event_chrome_is_neutralised():
    """FullCalendar paints a blue fill and white text over whatever
    eventContent returns. Without these overrides the chip never shows —
    this exact bug cost a debugging round during the design review."""
    for rule in ['.cal-surface .fc-event', '.cal-surface .fc-event-main']:
        assert rule in CSS, f'{rule} override missing'
    block = CSS[CSS.index('.cal-surface .fc-event,'):]
    block = block[:block.index('}')]
    assert 'background: transparent !important' in block
    assert 'color: inherit !important' in block


def test_the_chip_uses_a_left_rule_not_a_fill():
    """Color rides a 3px edge. Filling the chip breaks the suite status-dot
    rule and makes every row shout, so the one needing action stops standing
    out."""
    block = CSS[CSS.index('.cal-ev {'):]
    block = block[:block.index('}')]
    assert 'border-left: 3px solid' in block
    assert 'background: transparent' in block


def test_every_status_maps_to_an_edge_colour():
    for cls in ['.cal-ev.is-received', '.cal-ev.is-review', '.cal-ev.is-accepted',
                '.cal-ev.is-scheduled', '.cal-ev.is-needsinfo', '.cal-ev.is-hold',
                '.cal-ev.is-tentative', '.cal-ev.is-confirmed']:
        assert cls in CSS, f'{cls} has no edge colour'


def test_tentative_and_unsynced_share_the_hatch_vocabulary():
    """Both mean "not settled yet", so they read the same way — differing in
    colour, not in kind."""
    for cls in ['.cal-ev.is-tentative', '.cal-ev.is-unsynced']:
        block = CSS[CSS.index(cls):]
        block = block[:block.index('}')]
        assert 'repeating-linear-gradient' in block, f'{cls} lost its hatch'


def test_no_opacity_zero_in_calendar_rules():
    """Suite rule: an element that starts at opacity 0 stays invisible when its
    animation does not fire. Fixed suite-wide in keel 0.11.10; do not
    reintroduce it here."""
    calendar_css = CSS[CSS.index('   CALENDAR'):]
    assert 'opacity: 0;' not in calendar_css
    assert 'opacity:0;' not in calendar_css


def test_the_chip_has_a_visible_focus_state():
    """Every drag interaction needs a keyboard equivalent, and a keyboard user
    needs to see where they are."""
    assert '.cal-ev:focus-visible' in CSS


def test_mobile_drops_the_month_grid_rather_than_squeezing_it():
    """Seven columns on a 375px screen gives ~50px per day. The agenda list is
    the mobile design, not a fallback."""
    mobile = CSS[CSS.index('@media (max-width: 767px)'):]
    mobile = mobile[:mobile.index('\n}\n') + 3]
    assert '[data-view="dayGridMonth"]' in mobile
    assert 'display: none' in mobile


def test_mobile_touch_targets_meet_the_44px_floor():
    mobile = CSS[CSS.index('@media (max-width: 767px)'):]
    assert 'min-height: 44px' in mobile
    assert 'width: 44px' in mobile


@pytest.mark.parametrize('hardcoded', ['#0A2B4E', '#FAF7F2', '#B8860B'])
def test_calendar_rules_use_tokens_not_hardcoded_hex(hardcoded):
    """Colour belongs to the token layer. The rgba() hatch fills are the one
    exception — a gradient stop cannot take a var() alpha without a second
    token, and they are documented as such."""
    calendar_css = CSS[CSS.index('   CALENDAR'):]
    assert hardcoded not in calendar_css


def test_list_view_lets_the_chip_title_wrap():
    """The chip's nowrap ellipsis is right in a ~125px month cell and wrong in an
    agenda row. It also has a layout consequence: a table's `width: 100%` loses
    to its own min-content width, so a nowrap title made the list table grow past
    its container and the surface clipped every title. Scoped override, verified
    at 375px: table 315px inside a 319px surface, zero clipping."""
    assert '.cal-surface .fc-list-event .cal-ev-title' in CSS
    block = CSS[CSS.index('.cal-surface .fc-list-event .cal-ev-title'):]
    block = block[:block.index('}')]
    assert 'white-space: normal' in block
    assert 'text-overflow: clip' in block


def test_the_month_grid_keeps_its_ellipsis():
    """The wrap is scoped to list view; a month cell still truncates, because
    125px cannot hold a wrapped title without destroying the grid rhythm."""
    block = CSS[CSS.index('.cal-ev-title {'):]
    block = block[:block.index('}')]
    assert 'white-space: nowrap' in block
    assert 'text-overflow: ellipsis' in block
