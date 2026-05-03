"""Tests for ``keel.security.encryption``.

The encryption module is the dedicated KEK helper for data at rest. It
must not be coupled to ``SECRET_KEY``, must support rolling rotation
(MultiFernet), and must expose a clearly-documented legacy fallback for
products migrating off the old ``SECRET_KEY``-derived KEK.
"""
import base64
import hashlib

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from keel.security import encryption


pytest.importorskip('cryptography')


@pytest.fixture
def key():
    return encryption.generate_key()


@pytest.fixture
def second_key():
    return encryption.generate_key()


def test_round_trip_with_single_key(settings, key):
    settings.KEEL_ENCRYPTION_KEYS = key
    token = encryption.encrypt('top-secret')
    assert token != 'top-secret'
    assert encryption.decrypt(token) == 'top-secret'


def test_singular_setting_alias(settings, key):
    settings.KEEL_ENCRYPTION_KEYS = ''
    settings.KEEL_ENCRYPTION_KEY = key
    token = encryption.encrypt('hello')
    assert encryption.decrypt(token) == 'hello'


def test_unconfigured_raises(settings):
    settings.KEEL_ENCRYPTION_KEYS = ''
    settings.KEEL_ENCRYPTION_KEY = ''
    settings.KEEL_ENCRYPTION_LEGACY_SECRET_KEY_FALLBACK = False
    with pytest.raises(ImproperlyConfigured):
        encryption.encrypt('x')


def test_multikey_decrypts_old_ciphertext(settings, key, second_key):
    """Token written under old key must decrypt after a new key is added in front."""
    settings.KEEL_ENCRYPTION_KEYS = key
    old_token = encryption.encrypt('payload')

    settings.KEEL_ENCRYPTION_KEYS = f'{second_key},{key}'
    assert encryption.decrypt(old_token) == 'payload'


def test_multikey_encrypts_under_primary(settings, key, second_key):
    """New writes go through the first key; old key cannot decrypt them."""
    settings.KEEL_ENCRYPTION_KEYS = f'{second_key},{key}'
    new_token = encryption.encrypt('after-rotation')

    settings.KEEL_ENCRYPTION_KEYS = key
    from cryptography.fernet import InvalidToken
    with pytest.raises(InvalidToken):
        encryption.decrypt(new_token)


def test_rotate_re_encrypts_under_primary(settings, key, second_key):
    """``rotate()`` drains old-key ciphertext into the new key."""
    settings.KEEL_ENCRYPTION_KEYS = key
    old_token = encryption.encrypt('drain-me')

    settings.KEEL_ENCRYPTION_KEYS = f'{second_key},{key}'
    rotated = encryption.rotate(old_token)
    assert rotated != old_token

    settings.KEEL_ENCRYPTION_KEYS = second_key
    assert encryption.decrypt(rotated) == 'drain-me'


def test_legacy_secret_key_fallback(settings, key):
    """With the fallback flag set, ciphertext from the SECRET_KEY-derived
    KEK still decrypts under a fresh KEEL_ENCRYPTION_KEYS.
    """
    from cryptography.fernet import Fernet

    legacy_key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    legacy_token = Fernet(legacy_key).encrypt(b'legacy-payload').decode()

    settings.KEEL_ENCRYPTION_KEYS = key
    settings.KEEL_ENCRYPTION_LEGACY_SECRET_KEY_FALLBACK = True

    assert encryption.decrypt(legacy_token) == 'legacy-payload'


def test_legacy_fallback_disabled_by_default(settings, key):
    """Without the flag, legacy ciphertext does not decrypt — the whole point
    of the migration path is that you opt in once, drain, opt out.
    """
    from cryptography.fernet import Fernet, InvalidToken

    legacy_key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    legacy_token = Fernet(legacy_key).encrypt(b'legacy-payload').decode()

    settings.KEEL_ENCRYPTION_KEYS = key
    settings.KEEL_ENCRYPTION_LEGACY_SECRET_KEY_FALLBACK = False

    with pytest.raises(InvalidToken):
        encryption.decrypt(legacy_token)


def test_decrypt_accepts_str_and_bytes(settings, key):
    settings.KEEL_ENCRYPTION_KEYS = key
    token = encryption.encrypt('p')
    assert encryption.decrypt(token) == 'p'
    assert encryption.decrypt(token.encode()) == 'p'
