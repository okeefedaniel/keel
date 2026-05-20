"""Tests for keel.activity.dispatch._fan_out.

Regression coverage for the bug where _fan_out called notify() with kwargs that
didn't exist on its signature (user=, notification_type=, label=, activity=),
which caused every workflow-transition fan-out to silently TypeError-and-log.
"""
from types import SimpleNamespace
from unittest.mock import patch

from keel.activity.dispatch import _fan_out


def test_fan_out_invokes_notify_with_correct_kwargs():
    user = SimpleNamespace(pk=42)
    activity = SimpleNamespace(
        pk=7,
        verb='workflow.transitioned',
        deep_link='/projects/3/',
        source_label='Project alpha moved to Active',
    )

    with patch('keel.notifications.dispatch.notify') as mock_notify:
        _fan_out([user], activity)

    mock_notify.assert_called_once_with(
        event='activity.workflow.transitioned',
        recipients=[user],
        title='Project alpha moved to Active',
        link='/projects/3/',
    )


def test_fan_out_calls_notify_once_per_user():
    users = [SimpleNamespace(pk=i) for i in (1, 2, 3)]
    activity = SimpleNamespace(
        pk=1,
        verb='diligence.note_posted',
        deep_link='/x/',
        source_label='Note posted',
    )

    with patch('keel.notifications.dispatch.notify') as mock_notify:
        _fan_out(users, activity)

    assert mock_notify.call_count == 3
    assert [c.kwargs['recipients'] for c in mock_notify.call_args_list] == [
        [users[0]], [users[1]], [users[2]],
    ]


def test_fan_out_swallows_notify_exceptions():
    """A notify() failure for one user must not break the fan-out for the next."""
    users = [SimpleNamespace(pk=1), SimpleNamespace(pk=2)]
    activity = SimpleNamespace(
        pk=1,
        verb='workflow.transitioned',
        deep_link='/x/',
        source_label='X',
    )

    with patch('keel.notifications.dispatch.notify', side_effect=[RuntimeError('boom'), None]) as mock_notify:
        _fan_out(users, activity)

    assert mock_notify.call_count == 2
