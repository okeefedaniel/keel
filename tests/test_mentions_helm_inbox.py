"""Tests for keel.mentions.helm_inbox.build_inbox_items.

Pins:
- Returns [] for anonymous users
- Returns only user mentions (contacts excluded — they have no Helm inbox)
- Items conform to Helm UserInbox.items[] shape
"""
import uuid

import pytest
from django.contrib.contenttypes.models import ContentType

from keel.mentions.helm_inbox import build_inbox_items
from keel.mentions.models import MentionDelivery

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username='dok', email='dok@x.com', is_active=True,
    )


@pytest.fixture
def fake_note_ct(db):
    return ContentType.objects.get(app_label='keel_accounts', model='keeluser')


def test_anonymous_returns_empty():
    class Anon:
        is_authenticated = False
    assert build_inbox_items(Anon()) == []


def test_returns_user_mention_items(user, fake_note_ct):
    MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=uuid.uuid4(),
        recipient_kind=MentionDelivery.KIND_USER,
        recipient_user=user,
    )
    items = build_inbox_items(user)
    assert len(items) == 1
    item = items[0]
    assert item['type'] == 'mention'
    assert item['id'].startswith('mention:')
    assert 'title' in item
    assert 'deep_link' in item
    assert 'waiting_since' in item
    assert item['priority'] == 'medium'


def test_excludes_contact_mentions(user, fake_note_ct):
    """Contact mentions are not surfaced in the Helm inbox."""
    note_id = uuid.uuid4()
    # User mention (should appear)
    MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=note_id,
        recipient_kind=MentionDelivery.KIND_USER,
        recipient_user=user,
    )
    # Contact mention on same note (should NOT appear in user's inbox)
    MentionDelivery.objects.create(
        note_content_type=fake_note_ct,
        note_object_id=note_id,
        recipient_kind=MentionDelivery.KIND_CONTACT,
        recipient_ref='sarah',
    )
    items = build_inbox_items(user)
    assert len(items) == 1
    assert items[0]['type'] == 'mention'
