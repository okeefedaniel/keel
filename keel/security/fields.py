"""Custom Django model fields backed by ``keel.security.encryption``.

Provides ``EncryptedTextField`` for at-rest encryption of arbitrary
plaintext (API keys, OAuth refresh tokens, anything that should round-
trip cleartext to application code but never sit cleartext in the
database). Wraps ``Fernet``/``MultiFernet`` so:

- Reads decrypt under any configured key (rolling rotation supported).
- Writes encrypt under the primary (first) key.
- Empty values pass through as empty strings — no padding, no surprises.

Usage::

    from keel.security.fields import EncryptedTextField

    class KeelUser(AbstractUser):
        anthropic_api_key_encrypted = EncryptedTextField(blank=True, default='')

The cleartext is what application code sees on read; the column stores
ciphertext. ``MultiFernet`` ciphertext is always urlsafe-base64 ASCII,
so the underlying column is a plain ``TEXT``.

Failure mode: if the ciphertext can't be decrypted (key missing,
ciphertext truncated, ciphertext re-keyed past rotation), the field
returns an empty string AND logs a warning. The alternative — raising
on every read — would cascade into a 500 on any view that touches the
row, even when the encrypted column isn't used by that codepath.
Empty-on-failure means the user sees "no key configured" and can re-
enter rather than the page crashing.
"""

from __future__ import annotations

import logging

from django.db import models

logger = logging.getLogger(__name__)


class EncryptedTextField(models.TextField):
    """A ``TextField`` whose stored value is Fernet-encrypted.

    Cleartext on Python side, ciphertext at rest. Empty strings are
    stored as-is (no encryption) so an empty default doesn't trigger
    the encryption path during migrations.
    """

    description = 'Fernet-encrypted text (cleartext in Python, ciphertext at rest).'

    def from_db_value(self, value, expression, connection):
        """Decrypt on read. Returns '' on real ciphertext corruption, re-raises on transient errors.

        Two distinct failure modes deserve different handling:

        - ``cryptography.fernet.InvalidToken`` — the ciphertext genuinely
          can't be decrypted under any configured key (key rotation past
          the window, ciphertext truncated, wrong key entirely). The
          plaintext is unrecoverable. Return ``''`` so the surrounding
          view can render a "not configured" state instead of 500ing,
          and the user can re-enter the secret.

        - Any other ``Exception`` — likely transient (DB connection
          stutter, ImportError during boot, settings race). Re-raising
          surfaces the bug instead of silently treating a working
          encrypted column as empty. The caller's error handler is in
          a better position to decide than this field.

        See `/plan-eng-review` finding 1F.
        """
        if value is None or value == '':
            return value
        # Hard-require cryptography. Falling back to ``Exception`` would
        # make the InvalidToken-only catch swallow every error class
        # (DB stutter, settings race, anything) and silently return ''
        # — which would look identical to "user has no key" and erase
        # the work this branch did to differentiate the two failure
        # modes. cryptography is a transitive dep of every keel deploy
        # already; fail-closed if it's somehow missing.
        try:
            from cryptography.fernet import InvalidToken
        except ImportError as exc:  # pragma: no cover
            from django.core.exceptions import ImproperlyConfigured
            raise ImproperlyConfigured(
                'EncryptedTextField requires the cryptography package. '
                'Install with: pip install "keel[encryption]"'
            ) from exc
        try:
            from keel.security.encryption import decrypt
            return decrypt(value)
        except InvalidToken:
            logger.warning(
                'EncryptedTextField: ciphertext for %s.%s unreadable under any '
                'configured key — likely rotation past window. Returning empty '
                'string so the user can re-enter the secret.',
                type(self).__name__, self.attname,
            )
            return ''

    def to_python(self, value):
        """Forms hand back plaintext; nothing to do."""
        return value

    def get_prep_value(self, value):
        """Encrypt on write. Empty string stays empty (no ciphertext)."""
        if value is None:
            return None
        if value == '':
            return ''
        from keel.security.encryption import encrypt
        return encrypt(value)
