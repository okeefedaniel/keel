"""Tests for the declarative ``@scheduled_job(emits='verb.name')`` extension
to keel.scheduling.decorators (keel v0.47.0).

The decorator converts a structured ``handle()`` return value to one
``record_system_event()`` call, eliminating the "lazy author writes 'ok'"
risk that an explicit-call API carries. Routine OK summaries are pull-only;
failures fan out to system_admin notifications via the existing Activity →
Notification seam.

Tests focus on the conversion helper directly — it's a pure data transform.
Integration with the real handler / DB is exercised in the broader keel
test suite.
"""
from unittest.mock import patch

import pytest


def test_emit_converts_summary_only_dict_to_record_system_event_call():
    """Minimal contract: {'summary': '...'} produces one Activity row."""
    from keel.scheduling.decorators import _emit_system_event_from_handle_result

    with patch('keel.activity.services.record_system_event') as m:
        _emit_system_event_from_handle_result(
            verb='test.minimal',
            result={'summary': 'minimal handler returned this'},
        )

    assert m.called
    assert m.call_args.kwargs == {
        'verb': 'test.minimal',
        'summary': 'minimal handler returned this',
        'status': 'ok',  # default
        'metadata': {},  # no counts or metadata
    }


def test_emit_merges_counts_and_metadata():
    """counts and metadata both flow into the Activity row's metadata field."""
    from keel.scheduling.decorators import _emit_system_event_from_handle_result

    with patch('keel.activity.services.record_system_event') as m:
        _emit_system_event_from_handle_result(
            verb='grants_gov.polled',
            result={
                'summary': 'Grants.gov: +2 new, ~3 updated',
                'counts': {'new': 2, 'updated': 3, 'closed': 1, 'unchanged': 312},
                'status': 'ok',
                'metadata': {'duration_ms': 4220, 'source': 'simpler.grants.gov'},
            },
        )

    assert m.called
    md = m.call_args.kwargs['metadata']
    # counts wins on key collision (none here), all keys flow through
    assert md == {
        'duration_ms': 4220,
        'source': 'simpler.grants.gov',
        'new': 2, 'updated': 3, 'closed': 1, 'unchanged': 312,
    }
    assert m.call_args.kwargs['status'] == 'ok'


def test_emit_propagates_failed_status():
    """status='failed' must reach record_system_event so the notification
    pipeline fires for system_admin recipients."""
    from keel.scheduling.decorators import _emit_system_event_from_handle_result

    with patch('keel.activity.services.record_system_event') as m:
        _emit_system_event_from_handle_result(
            verb='salesforce.synced',
            result={
                'summary': 'Salesforce sync failed: 503 from upstream',
                'status': 'failed',
            },
        )

    assert m.call_args.kwargs['status'] == 'failed'


def test_emit_skips_when_handle_returns_none():
    """Legacy crons that haven't migrated to the structured contract — handle()
    returns None — keep working: CommandRun row is written by the outer wrapper,
    but no Activity row. A warning is logged."""
    from keel.scheduling.decorators import _emit_system_event_from_handle_result

    with patch('keel.activity.services.record_system_event') as m:
        _emit_system_event_from_handle_result(verb='legacy.cron', result=None)

    assert not m.called


def test_emit_skips_when_handle_returns_non_dict():
    """Same fail-soft behavior for non-dict return values (e.g. a bool)."""
    from keel.scheduling.decorators import _emit_system_event_from_handle_result

    with patch('keel.activity.services.record_system_event') as m:
        _emit_system_event_from_handle_result(verb='legacy.cron', result=42)
        _emit_system_event_from_handle_result(verb='legacy.cron', result='string')
        _emit_system_event_from_handle_result(verb='legacy.cron', result=True)

    assert not m.called


def test_emit_skips_when_dict_missing_summary():
    """summary is required — without it there's nothing to render on /ops/."""
    from keel.scheduling.decorators import _emit_system_event_from_handle_result

    with patch('keel.activity.services.record_system_event') as m:
        _emit_system_event_from_handle_result(
            verb='broken.cron',
            result={'counts': {'new': 5}, 'status': 'ok'},  # no 'summary' key
        )

    assert not m.called


def test_emit_counts_win_on_metadata_key_collision():
    """counts and metadata are both freeform dicts; if they collide on a key,
    counts wins. This is the structural rule — counts are the canonical
    numeric primitive, metadata is auxiliary context."""
    from keel.scheduling.decorators import _emit_system_event_from_handle_result

    with patch('keel.activity.services.record_system_event') as m:
        _emit_system_event_from_handle_result(
            verb='ambiguous.event',
            result={
                'summary': 'collision test',
                'counts': {'foo': 'from_counts'},
                'metadata': {'foo': 'from_metadata'},
            },
        )

    assert m.call_args.kwargs['metadata']['foo'] == 'from_counts'
