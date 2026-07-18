"""Tests for ``keel.notifications.digest.notify_batch``.

The primitive that stops the nightly-test email flood: many notify() items
collected inside a ``with`` block collapse into ONE aggregated notification
on exit, instead of one email per item.
"""
import pytest
from django.core import mail

from keel.notifications.digest import notify_batch, NotificationBatch


@pytest.fixture
def admin(db):
    from keel.accounts.models import KeelUser
    return KeelUser.objects.create_user(
        username='digest-admin', email='digest-admin@example.test',
        password='x', is_superuser=True, is_staff=True,
    )


def _outbox_to(user):
    return [m for m in mail.outbox if user.email in m.to]


def test_notify_batch_sends_single_notification(db, admin):
    with notify_batch(
        event='test_suite_failure',
        recipients=[admin],
        summary_title='Nightly tests: {count} new failure(s)',
    ) as batch:
        for i in range(5):
            batch.add(title=f'Failure {i}', detail='beacon')

    sent = _outbox_to(admin)
    assert len(sent) == 1
    # Count is accurate in the subject and the body lists every item.
    assert '5' in sent[0].subject
    assert 'Failure 0' in sent[0].body
    assert 'Failure 4' in sent[0].body


def test_notify_batch_empty_sends_nothing(db, admin):
    with notify_batch(event='test_suite_failure', recipients=[admin]) as batch:
        pass  # nothing added
    assert _outbox_to(admin) == []


def test_notify_batch_truncates_long_lists(db, admin):
    with notify_batch(
        event='test_suite_failure', recipients=[admin], item_limit=50,
    ) as batch:
        for i in range(60):
            batch.add(title=f'Failure {i}')

    sent = _outbox_to(admin)
    assert len(sent) == 1
    # 50 listed, 10 folded into a truncation line.
    assert '…and 10 more' in sent[0].body
    assert 'Failure 49' in sent[0].body
    assert 'Failure 59' not in sent[0].body


def test_individual_notifications_are_one_per_call(db, admin):
    """The single-submission path (a direct notify() per item) stays per-item.

    This is the behavior the digest deliberately does NOT change — three
    separate sends produce three emails; only the batch aggregates.
    """
    from keel.notifications.dispatch import notify

    for i in range(3):
        notify(
            event='test_suite_failure', recipients=[admin],
            title=f'Single {i}', message='body',
        )
    assert len(_outbox_to(admin)) == 3

    mail.outbox.clear()

    with notify_batch(event='test_suite_failure', recipients=[admin]) as batch:
        for i in range(3):
            batch.add(title=f'Batched {i}')
    assert len(_outbox_to(admin)) == 1


def test_notify_batch_body_survives_exception():
    """An exception inside the block propagates and sends nothing."""
    with pytest.raises(ValueError):
        with notify_batch(event='test_suite_failure', recipients=[]) as batch:
            batch.add(title='partial')
            raise ValueError('boom')
    # No recipients + we raised, so nothing to assert on outbox beyond emptiness.
    assert mail.outbox == []


def test_batch_len():
    b = NotificationBatch()
    assert len(b) == 0
    b.add(title='x')
    assert len(b) == 1
