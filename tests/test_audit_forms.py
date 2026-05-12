"""Tests for keel_site.audit.forms.AuditFilterForm."""
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils import timezone

from keel_site.audit.forms import AuditFilterForm, MAX_WINDOW


def test_unbound_form_returns_default_24h_window():
    """C1 regression: an unbound form falls back to last-24h without crashing.

    The view always binds the form (request.GET, even if empty), but the
    fallback path inside cleaned_window must still be safe.
    """
    form = AuditFilterForm({}, visible_products=[])
    form.is_valid()
    start, end = form.cleaned_window()
    delta = end - start
    assert timedelta(hours=23, minutes=59) < delta < timedelta(hours=24, minutes=1)
    assert start.tzinfo is not None and end.tzinfo is not None


def test_preset_1h_window():
    form = AuditFilterForm({'window': '1h'}, visible_products=[])
    form.is_valid()
    start, end = form.cleaned_window()
    delta = end - start
    assert timedelta(minutes=59) < delta < timedelta(minutes=61)


def test_preset_30d_window():
    form = AuditFilterForm({'window': '30d'}, visible_products=[])
    form.is_valid()
    start, end = form.cleaned_window()
    delta = end - start
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, hours=1)


def test_custom_window_with_explicit_bounds():
    form = AuditFilterForm({
        'window': 'custom',
        'window_from': '2026-05-01T00:00:00',
        'window_to': '2026-05-02T00:00:00',
    }, visible_products=[])
    assert form.is_valid()
    start, end = form.cleaned_window()
    assert (end - start) == timedelta(days=1)
    assert start.tzinfo is not None and end.tzinfo is not None


def test_custom_window_input_is_tz_aware():
    """Decision A8: cleaned_window always returns tz-aware datetimes.

    Django's DateTimeField stamps the project's TIME_ZONE when USE_TZ
    is on (NY for Keel's settings), so we assert tz-aware rather than
    strictly UTC. The window math is timezone-correct either way.
    """
    form = AuditFilterForm({
        'window': 'custom',
        'window_from': '2026-05-01T00:00:00',
        'window_to': '2026-05-01T12:00:00',
    }, visible_products=[])
    assert form.is_valid()
    start, end = form.cleaned_window()
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    # Round-trip duration is preserved
    assert (end - start) == timedelta(hours=12)


def test_custom_window_from_after_to_rejected():
    form = AuditFilterForm({
        'window': 'custom',
        'window_from': '2026-05-02T00:00:00',
        'window_to': '2026-05-01T00:00:00',
    }, visible_products=[])
    assert form.is_valid() is False


def test_custom_window_exceeds_max_rejected_by_clean():
    """The form's clean() raises ValidationError above MAX_WINDOW."""
    form = AuditFilterForm({
        'window': 'custom',
        'window_from': '2020-01-01T00:00:00',
        'window_to': '2026-05-01T00:00:00',
    }, visible_products=[])
    assert form.is_valid() is False


def test_products_choices_restricted_to_visible():
    form = AuditFilterForm({
        'products': ['beacon', 'something-else'],
    }, visible_products=['beacon'])
    assert form.is_valid() is False
    assert 'products' in form.errors


def test_products_visible_choice_accepted():
    form = AuditFilterForm({
        'products': ['beacon'],
    }, visible_products=['beacon', 'harbor'])
    assert form.is_valid()
    assert form.cleaned_data['products'] == ['beacon']


def test_q_keyword_passes_through():
    form = AuditFilterForm({'q': 'dan'}, visible_products=[])
    assert form.is_valid()
    assert form.cleaned_data['q'] == 'dan'
