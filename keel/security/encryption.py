"""Application-level encryption for data at rest.

Provides a Fernet-backed encrypt/decrypt helper that reads its key material
from ``KEEL_ENCRYPTION_KEYS`` (or ``KEEL_ENCRYPTION_KEY``), independent of
Django's ``SECRET_KEY``. Supports rolling key rotation via ``MultiFernet``:
the first key in the list is the active key (used for new encryptions);
any remaining keys are accepted for decryption only.

Why this is separate from ``SECRET_KEY``: ``SECRET_KEY`` rotates session
signing, CSRF tokens, and signed cookies. The Key Encryption Key (KEK) for
data at rest must rotate on a different cadence — leaking a session secret
should not require re-encrypting every encrypted column in the database,
and rotating the KEK should not invalidate every active session.

Setup
-----

Generate a key::

    python -c "from keel.security.encryption import generate_key; print(generate_key())"

Set on the deployment::

    KEEL_ENCRYPTION_KEYS=<base64-fernet-key>

Rotation procedure (zero-downtime, no big-bang re-encrypt)
----------------------------------------------------------

1. Generate a new key with ``generate_key()``.
2. Set ``KEEL_ENCRYPTION_KEYS=<NEW>,<OLD>`` (new key first). Redeploy.
   Reads keep working under either key; new writes use ``<NEW>``.
3. Run ``python manage.py rotate_encryption_keys`` (per-product command;
   each product registers the encrypted fields it wants rotated). The
   command reads + re-saves every encrypted record so all ciphertext is
   under ``<NEW>``.
4. Drop ``<OLD>``: set ``KEEL_ENCRYPTION_KEYS=<NEW>``. Redeploy.

Migration from a SECRET_KEY-derived KEK
----------------------------------------

Products that previously derived their Fernet key from ``SECRET_KEY``
(``BountyProfile`` did this until keel 0.25.0) can opt into a one-time
fallback during the rotation window::

    KEEL_ENCRYPTION_KEYS=<NEW>
    KEEL_ENCRYPTION_LEGACY_SECRET_KEY_FALLBACK=true

When the fallback flag is set, ``Fernet(sha256(SECRET_KEY))`` is appended
to the decrypt list so legacy ciphertext keeps reading. Run
``rotate_encryption_keys`` to re-encrypt everything under ``<NEW>``, then
unset the flag and rotate ``SECRET_KEY`` independently.
"""

from __future__ import annotations

import base64
import hashlib
import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _split_keys(value: str) -> list[str]:
    return [k.strip() for k in value.split(',') if k.strip()]


def _legacy_key_from_secret(secret_key: str) -> bytes:
    """Compatibility: the SECRET_KEY-derived Fernet key used pre-0.25.0.

    Matches the construction in ``bounty.core.models.BountyProfile._get_fernet``.
    """
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _load_keys() -> list[str]:
    raw = getattr(settings, 'KEEL_ENCRYPTION_KEYS', '') or os.environ.get('KEEL_ENCRYPTION_KEYS', '')
    keys = _split_keys(raw) if raw else []

    if not keys:
        single = getattr(settings, 'KEEL_ENCRYPTION_KEY', '') or os.environ.get('KEEL_ENCRYPTION_KEY', '')
        if single:
            keys = [single.strip()]

    legacy_fallback = getattr(settings, 'KEEL_ENCRYPTION_LEGACY_SECRET_KEY_FALLBACK', False) or \
        (os.environ.get('KEEL_ENCRYPTION_LEGACY_SECRET_KEY_FALLBACK', '').lower() in ('1', 'true', 'yes'))
    if legacy_fallback:
        keys.append(_legacy_key_from_secret(settings.SECRET_KEY).decode())

    if not keys:
        raise ImproperlyConfigured(
            'keel.security.encryption requires KEEL_ENCRYPTION_KEYS (or '
            'KEEL_ENCRYPTION_KEY) to be set. Generate one with '
            'keel.security.encryption.generate_key().'
        )
    return keys


def _build_multi_fernet(keys: list[str]):
    try:
        from cryptography.fernet import Fernet, MultiFernet
    except ImportError as exc:  # pragma: no cover
        raise ImproperlyConfigured(
            'keel.security.encryption requires the cryptography package. '
            'Install with: pip install "keel[encryption]"'
        ) from exc
    fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
    return MultiFernet(fernets)


def get_fernet():
    """Return a ``MultiFernet`` built from the current key configuration.

    Reads settings on every call so tests can monkey-patch keys without
    importing internals. Cheap — Fernet construction is just key parsing.
    """
    return _build_multi_fernet(_load_keys())


def encrypt(plaintext: str | bytes) -> str:
    """Encrypt under the primary (first) configured key. Returns urlsafe text."""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    return get_fernet().encrypt(plaintext).decode()


def decrypt(ciphertext: str | bytes) -> str:
    """Decrypt under any configured key. Returns the plaintext string."""
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode()
    return get_fernet().decrypt(ciphertext).decode()


def rotate(ciphertext: str | bytes) -> str:
    """Re-encrypt ``ciphertext`` under the primary key.

    No-op if it's already under the primary key. Use during key rotation
    to drain old-key ciphertext without changing plaintext.
    """
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode()
    return get_fernet().rotate(ciphertext).decode()


def generate_key() -> str:
    """Generate a new Fernet key. Print + paste into KEEL_ENCRYPTION_KEYS."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise ImproperlyConfigured(
            'keel.security.encryption requires the cryptography package.'
        ) from exc
    return Fernet.generate_key().decode()
