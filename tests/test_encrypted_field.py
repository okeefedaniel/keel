"""Tests for ``keel.security.fields.EncryptedTextField``.

Round-trips plaintext through the encrypted column on ``KeelUser``
without leaking ciphertext into application code.
"""

import pytest

from keel.accounts.models import KeelUser, Organization
from keel.security import encryption


pytest.importorskip('cryptography')


@pytest.fixture
def org(db):
    return Organization.objects.create(slug='enc-test-org', name='Enc Test')


@pytest.fixture
def user(db, org, settings):
    settings.KEEL_ENCRYPTION_KEYS = encryption.generate_key()
    return KeelUser.objects.create(
        username='enc-user', email='enc@example.test', organization=org,
    )


def test_plaintext_round_trip(db, user, settings):
    user.anthropic_api_key = 'sk-ant-secret-1234567890abcdef'
    user.save(update_fields=['anthropic_api_key_encrypted'])

    # Reload from DB so from_db_value runs.
    fresh = KeelUser.objects.get(pk=user.pk)
    assert fresh.anthropic_api_key == 'sk-ant-secret-1234567890abcdef'


def test_ciphertext_at_rest_is_not_plaintext(db, user, settings):
    """Verify what's actually stored is ciphertext, not plaintext.

    ``values_list`` still routes through ``from_db_value``, so use a
    raw SQL query to bypass the field converter and see what's
    physically in the column. The query must run on the same
    connection the ORM uses so the test-transaction's writes are
    visible to it.
    """
    from django.db import connection

    user.anthropic_api_key = 'sk-ant-cleartext-here-9876543210'
    user.save(update_fields=['anthropic_api_key_encrypted'])

    # Use connection.connection.cursor() to share the test transaction
    # connection, then query without the parametrized id (small tables,
    # only a single test user row).
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT anthropic_api_key_encrypted FROM keel_user '
            "WHERE username = 'enc-user'"
        )
        row = cursor.fetchone()

    assert row is not None, 'expected one row for enc-user'
    raw = row[0]
    assert raw != 'sk-ant-cleartext-here-9876543210'
    assert 'sk-ant-cleartext' not in (raw or '')
    # MultiFernet ciphertext is urlsafe-base64; should be 100+ chars.
    assert len(raw or '') > 50


def test_empty_string_stays_empty(db, user, settings):
    user.anthropic_api_key = ''
    user.save(update_fields=['anthropic_api_key_encrypted'])

    raw = KeelUser.objects.filter(pk=user.pk).values_list(
        'anthropic_api_key_encrypted', flat=True,
    ).first()
    assert raw == ''
    fresh = KeelUser.objects.get(pk=user.pk)
    assert fresh.has_anthropic_key() is False


def test_hint_is_last_4(db, user, settings):
    user.anthropic_api_key = 'sk-ant-1234567890abcdef-XYZ9'
    user.save(update_fields=['anthropic_api_key_encrypted'])
    fresh = KeelUser.objects.get(pk=user.pk)
    assert fresh.anthropic_key_hint().endswith('XYZ9')
    assert 'sk-ant' not in fresh.anthropic_key_hint()
