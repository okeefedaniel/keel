"""Tests for the polymorphic MentionDelivery model.

Pins the constraints:

1. CheckConstraint blocks ill-formed rows
   - kind=user must have recipient_user populated AND recipient_ref=''
   - kind=contact must have recipient_user=None
2. UniqueConstraint prevents double-write for user mentions on same note
3. UniqueConstraint prevents double-write for contact mentions on same note
4. Concurrent inserts hit IntegrityError (caller handles via get_or_create)
"""
import uuid

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create(username='alice', email='a@x.com')


@pytest.fixture
def fake_note_ct(db):
    """Use the User ContentType as a stand-in for a real note CT.

    The MentionDelivery.note Generic FK doesn't actually resolve in
    these tests (we never call .note); we just need a valid CT pk +
    object_id pair.
    """
    return ContentType.objects.get(app_label='keel_accounts', model='keeluser')


def test_user_mention_row_ok(user, fake_note_ct):
    from keel.mentions.models import MentionDelivery
    row = MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=uuid.uuid4(),
        recipient_kind=MentionDelivery.KIND_USER,
        recipient_user=user,
    )
    assert row.pk is not None


def test_contact_mention_row_ok(fake_note_ct):
    from keel.mentions.models import MentionDelivery
    row = MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=uuid.uuid4(),
        recipient_kind=MentionDelivery.KIND_CONTACT,
        recipient_ref='sarah-jones',
        recipient_peer_url='https://beacon.example/c/sarah-jones',
    )
    assert row.pk is not None


def test_user_kind_without_user_blocked(fake_note_ct):
    """CheckConstraint: kind=user requires recipient_user populated."""
    from keel.mentions.models import MentionDelivery
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MentionDelivery.objects.create(
                note_content_type=fake_note_ct,
                note_object_id=uuid.uuid4(),
                recipient_kind=MentionDelivery.KIND_USER,
                recipient_user=None,
            )


def test_contact_kind_with_user_blocked(user, fake_note_ct):
    """CheckConstraint: kind=contact requires recipient_user IS NULL."""
    from keel.mentions.models import MentionDelivery
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MentionDelivery.objects.create(
                note_content_type=fake_note_ct,
                note_object_id=uuid.uuid4(),
                recipient_kind=MentionDelivery.KIND_CONTACT,
                recipient_user=user,
                recipient_ref='sarah-jones',
            )


def test_duplicate_user_mention_for_same_note_blocked(user, fake_note_ct):
    from keel.mentions.models import MentionDelivery
    note_id = uuid.uuid4()
    MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=note_id,
        recipient_kind=MentionDelivery.KIND_USER,
        recipient_user=user,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MentionDelivery.objects.create(
                note_content_type=fake_note_ct,
                note_object_id=note_id,
                recipient_kind=MentionDelivery.KIND_USER,
                recipient_user=user,
            )


def test_duplicate_contact_mention_for_same_note_blocked(fake_note_ct):
    from keel.mentions.models import MentionDelivery
    note_id = uuid.uuid4()
    MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=note_id,
        recipient_kind=MentionDelivery.KIND_CONTACT,
        recipient_ref='sarah-jones',
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MentionDelivery.objects.create(
                note_content_type=fake_note_ct,
                note_object_id=note_id,
                recipient_kind=MentionDelivery.KIND_CONTACT,
                recipient_ref='sarah-jones',
            )


def test_different_kinds_for_same_note_ok(user, fake_note_ct):
    """A user mention and a contact mention on the same note coexist."""
    from keel.mentions.models import MentionDelivery
    note_id = uuid.uuid4()
    MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=note_id,
        recipient_kind=MentionDelivery.KIND_USER,
        recipient_user=user,
    )
    MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=note_id,
        recipient_kind=MentionDelivery.KIND_CONTACT,
        recipient_ref='sarah-jones',
    )
    assert MentionDelivery.objects.filter(note_object_id=note_id).count() == 2
