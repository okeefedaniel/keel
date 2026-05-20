"""Tests for the ``audit_constraint_present`` canary gauge (v0.46.0).

The canary builds a payload with five flags now (Approach D added one):

- ``audit_silent_24h``
- ``cron_silent_24h``
- ``cron_failures_24h``
- ``notifications_failing``
- ``audit_constraint_missing`` — flagged when we measured ``audit_constraint_present == False``

The gauge resolves the constraint via ``information_schema.check_constraints``
on Postgres. On SQLite (the test backend) the gauge returns None, the flag
stays False, and no false positive surfaces.
"""
from unittest.mock import patch

import pytest


def test_check_audit_constraint_present_returns_none_on_non_postgres():
    """SQLite doesn't expose check_constraints via information_schema — the
    gauge must return None so the flag stays disabled (no false positive)."""
    from keel.ops.canary import _check_audit_constraint_present
    result = _check_audit_constraint_present()
    # On the test SQLite backend, vendor != 'postgresql' → None.
    assert result is None


def test_build_canary_payload_exposes_audit_constraint_present_key():
    """The payload should always carry the key, even when the gauge couldn't
    measure it. Consumers (templates, /ops/ chips) should treat None as
    'not measured' rather than 'broken'."""
    from keel.ops.canary import build_canary_payload
    payload = build_canary_payload()
    assert 'audit_constraint_present' in payload
    # On non-postgres backends the value should be None.
    assert payload['audit_constraint_present'] is None


def test_audit_constraint_missing_flag_only_when_gauge_returned_false():
    """The flag triggers ONLY on the explicit False reading. None must NOT
    trip the flag — that's the whole point of the three-state gauge."""
    from keel.ops.canary import build_canary_payload

    # Force the gauge to return False (constraint missing).
    with patch('keel.ops.canary._check_audit_constraint_present',
               return_value=False):
        payload = build_canary_payload()
    assert payload['flags']['audit_constraint_missing'] is True
    assert payload['healthy'] is False  # flag tripped → not healthy

    # Force True (constraint present).
    with patch('keel.ops.canary._check_audit_constraint_present',
               return_value=True):
        payload = build_canary_payload()
    assert payload['flags']['audit_constraint_missing'] is False

    # Force None (gauge couldn't measure).
    with patch('keel.ops.canary._check_audit_constraint_present',
               return_value=None):
        payload = build_canary_payload()
    assert payload['flags']['audit_constraint_missing'] is False


def test_flag_labels_includes_audit_constraint_missing():
    """The label dict drives the chip rendering on /ops/ — every flag must
    have a human-readable label or the chip falls back to the raw key."""
    from keel.ops.canary import FLAG_LABELS
    assert 'audit_constraint_missing' in FLAG_LABELS
    assert FLAG_LABELS['audit_constraint_missing']
