"""Tests for bulk / automated ChangeRequest ingestion.

Covers the fix for the nightly-test email flood:

- 50 failures created through the bulk path -> exactly ONE digest email.
- A single human submission still notifies per item.
- Dedupe against currently-open requests is preserved.
- The batch ingest endpoint and the per-item automated-suppression gate.
"""
import json

import pytest
from django.core import mail
from django.test import override_settings

from keel.requests.models import ChangeRequest, Status
from keel.requests.services import bulk_ingest_change_requests
from keel.requests.views import _is_automated_submission


@pytest.fixture
def admin(db):
    from keel.accounts.models import KeelUser
    return KeelUser.objects.create_user(
        username='cr-admin', email='cr-admin@example.test',
        password='x', is_superuser=True, is_staff=True,
    )


def _outbox_to(user):
    return [m for m in mail.outbox if user.email in m.to]


def _items(n, prefix='Failure'):
    return [
        {
            'title': f'{prefix} {i}',
            'description': f'detail {i}',
            'product': 'beacon',
            'category': 'bug',
            'priority': 'high',
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Bulk path: N rows -> 1 notification
# ---------------------------------------------------------------------------
def test_bulk_ingest_creates_all_rows_and_sends_one_digest(db, admin):
    result = bulk_ingest_change_requests(
        _items(50),
        recipients=[admin],
        summary_title='Nightly tests: {count} new failure(s)',
    )

    assert result['created'] == 50
    assert result['skipped'] == 0
    assert ChangeRequest.objects.count() == 50

    sent = _outbox_to(admin)
    assert len(sent) == 1
    assert '50' in sent[0].subject  # accurate count in the body


def test_bulk_ingest_default_recipients_are_superusers(db, admin):
    """With no explicit recipients, active superusers get the single digest."""
    result = bulk_ingest_change_requests(_items(3))
    assert result['created'] == 3
    assert len(_outbox_to(admin)) == 1


def test_bulk_ingest_dedupes_open_requests(db, admin):
    # An already-open request with a matching title must not be recreated.
    ChangeRequest.objects.create(
        title='Failure 0', description='pre-existing',
        product='beacon', status=Status.PENDING,
    )

    result = bulk_ingest_change_requests(
        _items(3),  # Failure 0, 1, 2 — 0 is a dupe of the open row
        recipients=[admin],
    )

    assert result['created'] == 2  # Failure 1, 2
    assert result['skipped'] == 1  # Failure 0 deduped
    # Original + 2 new = 3 total rows, but only one row titled 'Failure 0'.
    assert ChangeRequest.objects.filter(title='Failure 0').count() == 1
    assert ChangeRequest.objects.count() == 3

    sent = _outbox_to(admin)
    assert len(sent) == 1
    assert '2' in sent[0].subject


def test_bulk_ingest_skips_incomplete_items(db, admin):
    items = [
        {'title': 'Good', 'description': 'ok', 'product': 'beacon'},
        {'title': 'No description', 'product': 'beacon'},  # missing description
        {'description': 'No title', 'product': 'beacon'},  # missing title
    ]
    result = bulk_ingest_change_requests(items, recipients=[admin])
    assert result['created'] == 1
    assert result['skipped'] == 2


def test_bulk_ingest_silent_when_notify_admins_false(db, admin):
    result = bulk_ingest_change_requests(
        _items(4), notify_admins=False,
    )
    assert result['created'] == 4
    assert _outbox_to(admin) == []


def test_bulk_ingest_empty_creates_nothing(db, admin):
    result = bulk_ingest_change_requests([], recipients=[admin])
    assert result == {'created': 0, 'skipped': 0, 'ids': []}
    assert _outbox_to(admin) == []


# ---------------------------------------------------------------------------
# Automated-submission detection
# ---------------------------------------------------------------------------
def test_is_automated_submission():
    assert _is_automated_submission('Nightly Test Bot') is True
    assert _is_automated_submission('nightly test bot') is True
    assert _is_automated_submission('  Nightly Security Audit ') is True
    assert _is_automated_submission('Dan') is False
    assert _is_automated_submission('') is False
    assert _is_automated_submission(None) is False


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@override_settings(KEEL_API_KEY='test-ingest-key')
def test_api_ingest_batch_endpoint_sends_one_digest(db, admin, client):
    payload = {
        'items': _items(20),
        'summary_title': 'Nightly tests: {count} new failure(s)',
        'submitted_by_name': 'Nightly Test Bot',
    }
    resp = client.post(
        '/api/requests/ingest/batch/',
        data=json.dumps(payload),
        content_type='application/json',
        HTTP_AUTHORIZATION='Bearer test-ingest-key',
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body['created'] == 20
    assert ChangeRequest.objects.count() == 20
    # One digest for the whole batch, not 20 emails.
    assert len(_outbox_to(admin)) == 1


@override_settings(KEEL_API_KEY='test-ingest-key')
def test_api_ingest_batch_rejects_bad_key(db, client):
    resp = client.post(
        '/api/requests/ingest/batch/',
        data=json.dumps({'items': []}),
        content_type='application/json',
        HTTP_AUTHORIZATION='Bearer wrong',
    )
    assert resp.status_code == 401
    assert ChangeRequest.objects.count() == 0


@override_settings(KEEL_API_KEY='test-ingest-key')
def test_api_ingest_single_automated_submission_suppresses_email(db, admin, client):
    """A bot POSTing one-at-a-time to the legacy endpoint creates the row but
    fires no per-item email — the flood can't recur even pre-migration."""
    payload = {
        'title': 'Nightly Test Failure: X',
        'description': 'boom',
        'product': 'beacon',
        'submitted_by_name': 'Nightly Test Bot',
    }
    resp = client.post(
        '/api/requests/ingest/',
        data=json.dumps(payload),
        content_type='application/json',
        HTTP_AUTHORIZATION='Bearer test-ingest-key',
    )
    assert resp.status_code == 201
    assert ChangeRequest.objects.filter(submitted_by_name='Nightly Test Bot').count() == 1
    assert _outbox_to(admin) == []


def test_notify_admins_api_single_human_submission_emails_once(db, admin):
    """The human single-submission path still notifies admins per item."""
    from keel.requests.views import _notify_admins_api

    cr = ChangeRequest.objects.create(
        title='A real bug', description='from the widget',
        product='beacon', submitted_by_name='Dan O.',
    )
    _notify_admins_api(cr)

    # Exactly one notification addressed to the admin (boswell/sms fan-out
    # goes elsewhere; the admin's own inbox gets one).
    sent = _outbox_to(admin)
    assert len(sent) == 1
    assert sent[0].subject.startswith('New ')
