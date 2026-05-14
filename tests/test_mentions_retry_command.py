"""Tests for `manage.py retry_failed_mention_deliveries`.

Pins:
- No-op when Beacon is not configured (no requests sent; clear stderr message)
- Skips rows with peer_status=ok or empty (only failed/gone are processed)
- Successful retry flips peer_status to ok and clears peer_error
- Failed retry keeps peer_status=failed and updates peer_error
- 410 response flips peer_status to gone
- --dry-run sends zero requests
- --include-gone also picks up gone rows
- Source note deleted between dispatch + retry → SKIP, no crash
- --limit caps the batch size
"""
import uuid
from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import override_settings

from keel.mentions.models import MentionDelivery


pytestmark = pytest.mark.django_db


@pytest.fixture
def note_ct(db):
    """Use KeelUser CT as a generic stand-in 'note'.

    The retry command resolves the note via ContentType.get_for_id(...)
    .get(pk=note_object_id). To exercise the dispatch path, each test
    creates a real KeelUser and uses its pk as note_object_id. Tests
    that want to exercise the missing-note path use a random UUID
    instead.
    """
    return ContentType.objects.get(app_label='keel_accounts', model='keeluser')


@pytest.fixture
def fake_note(django_user_model):
    """A KeelUser instance that stands in for a 'note' in tests.

    The retry command reads note.content and note.author for the retry
    payload. KeelUser has neither, so we tack them on as attributes
    (Django doesn't care for our test purposes — the resolve path uses
    getattr with defaults).
    """
    user = django_user_model.objects.create_user(
        username='dok-test', email='dok-test@x.com',
    )
    # Stash placeholders that the retry command reads with getattr().
    user.content = 'hey @beacon:sarah-jones'
    user.author = user
    return user


def _row(ct, status, slug='sarah-jones', url='https://harbor.example/app/1/',
         note_pk=None):
    return MentionDelivery.objects.create(
        note_content_type=ct,
        note_object_id=note_pk if note_pk is not None else uuid.uuid4(),
        recipient_kind=MentionDelivery.KIND_CONTACT,
        recipient_ref=slug,
        recipient_peer_url=url,
        peer_status=status,
        peer_error='boom' if status == MentionDelivery.PEER_FAILED else '',
    )


@override_settings(BEACON_INTAKE_URL='', BEACON_INTAKE_API_KEY='')
def test_no_op_when_beacon_unconfigured(note_ct):
    _row(note_ct, MentionDelivery.PEER_FAILED)
    out, err = StringIO(), StringIO()
    call_command('retry_failed_mention_deliveries', stdout=out, stderr=err)
    assert 'Beacon is not configured' in err.getvalue()


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_succeeded_when_no_failed_rows():
    out = StringIO()
    call_command('retry_failed_mention_deliveries', stdout=out)
    assert 'No failed contact mentions' in out.getvalue()


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_retry_success_flips_to_ok(note_ct, fake_note):
    row = _row(note_ct, MentionDelivery.PEER_FAILED, note_pk=fake_note.pk)
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
        return_value=(True, ''),
    ):
        out = StringIO()
        call_command('retry_failed_mention_deliveries', stdout=out)
    row.refresh_from_db()
    assert row.peer_status == MentionDelivery.PEER_OK
    assert row.peer_error == ''


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_retry_failure_keeps_failed(note_ct, fake_note):
    row = _row(note_ct, MentionDelivery.PEER_FAILED, note_pk=fake_note.pk)
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
        return_value=(False, 'connection refused'),
    ):
        out = StringIO()
        call_command('retry_failed_mention_deliveries', stdout=out)
    row.refresh_from_db()
    assert row.peer_status == MentionDelivery.PEER_FAILED
    assert 'connection refused' in row.peer_error


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_410_flips_to_gone(note_ct, fake_note):
    row = _row(note_ct, MentionDelivery.PEER_FAILED, note_pk=fake_note.pk)
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
        return_value=(False, 'gone'),
    ):
        call_command('retry_failed_mention_deliveries', stdout=StringIO())
    row.refresh_from_db()
    assert row.peer_status == MentionDelivery.PEER_GONE


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_skips_ok_rows(note_ct):
    row = _row(note_ct, MentionDelivery.PEER_OK)
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
    ) as mocked:
        call_command('retry_failed_mention_deliveries', stdout=StringIO())
    mocked.assert_not_called()
    row.refresh_from_db()
    assert row.peer_status == MentionDelivery.PEER_OK


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_skips_gone_by_default_but_includes_with_flag(note_ct, fake_note):
    gone_row = _row(note_ct, MentionDelivery.PEER_GONE, note_pk=fake_note.pk)
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
    ) as mocked:
        # Default: skips gone
        call_command('retry_failed_mention_deliveries', stdout=StringIO())
    mocked.assert_not_called()

    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
        return_value=(False, 'gone'),
    ) as mocked:
        # --include-gone: picks them up
        call_command(
            'retry_failed_mention_deliveries',
            '--include-gone',
            stdout=StringIO(),
        )
    mocked.assert_called_once()


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_dry_run_sends_no_requests(note_ct):
    row = _row(note_ct, MentionDelivery.PEER_FAILED)
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
    ) as mocked:
        call_command('retry_failed_mention_deliveries', '--dry-run', stdout=StringIO())
    mocked.assert_not_called()
    row.refresh_from_db()
    assert row.peer_status == MentionDelivery.PEER_FAILED  # unchanged


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_missing_source_note_is_skipped(note_ct):
    # Fabricate a row whose note_object_id doesn't resolve to any row in
    # the keel_accounts.KeelUser table. The retry should skip silently
    # (not raise) and leave the row's peer_status alone.
    row = _row(note_ct, MentionDelivery.PEER_FAILED)
    # note_object_id is a random UUID — no KeelUser row matches it.
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
    ) as mocked:
        call_command('retry_failed_mention_deliveries', stdout=StringIO(), stderr=StringIO())
    mocked.assert_not_called()
    row.refresh_from_db()
    assert row.peer_status == MentionDelivery.PEER_FAILED  # untouched


@override_settings(
    BEACON_INTAKE_URL='https://beacon.example/',
    BEACON_INTAKE_API_KEY='secret',
)
def test_limit_caps_batch(note_ct, fake_note):
    # Create 5 failed rows pointing at the same fake note; --limit=2 should process only 2.
    for i in range(5):
        _row(note_ct, MentionDelivery.PEER_FAILED, slug=f'contact-{i}',
             note_pk=fake_note.pk)
    with patch(
        'keel.mentions.management.commands.retry_failed_mention_deliveries.append_contact_mention',
        return_value=(False, 'still down'),
    ) as mocked:
        call_command('retry_failed_mention_deliveries', '--limit', '2', stdout=StringIO())
    # Each call iterates one row + one beacon call; --limit=2 means 2 calls max.
    assert mocked.call_count == 2
