"""Guard against the password-reset email-relay abuse.

allauth's default ``ACCOUNT_PREVENT_ENUMERATION = True`` makes the public,
unauthenticated ``/accounts/password/reset/`` endpoint email a note to any
address that has NO account ("someone tried to access an account with this
email"). An attacker scripts scraped third-party addresses through the form
and every product becomes an open relay mailing strangers from
``info@docklabs.ai`` — cold mail that torched the sending domain's
reputation in 2026-07 (97 of 100 outbound emails were these).

``KeelAccountAdapter.send_mail`` drops the ``account/email/unknown_account``
template suite-wide so the send never happens, while allauth's neutral
"check your email" *response* is preserved (no enumeration regression).

These tests call the REAL ``KeelAccountAdapter.send_mail`` and patch only
the allauth superclass send, so a future refactor of the override is
actually exercised.
"""
from unittest import mock

import pytest
from django.test import override_settings

pytest.importorskip("allauth")

from allauth.account.adapter import DefaultAccountAdapter  # noqa: E402
from keel.core.sso import KeelAccountAdapter  # noqa: E402

UNKNOWN = "account/email/unknown_account"
LEGIT = "account/email/password_reset_key"


def _adapter():
    # BaseAdapter.__init__ accepts request=None — no DB or request needed.
    return KeelAccountAdapter(request=None)


def test_unknown_account_mail_is_suppressed_by_default():
    adapter = _adapter()
    with mock.patch.object(DefaultAccountAdapter, "send_mail") as parent:
        result = adapter.send_mail(UNKNOWN, "stranger@example.com", {})
    assert result is None
    parent.assert_not_called()  # nothing left the building


def test_legit_mail_still_sends():
    adapter = _adapter()
    with mock.patch.object(DefaultAccountAdapter, "send_mail", return_value="sent") as parent:
        result = adapter.send_mail(LEGIT, "real@user.com", {})
    assert result == "sent"
    parent.assert_called_once()


@override_settings(KEEL_EMAIL_UNKNOWN_ACCOUNTS=True)
def test_opt_in_restores_unknown_account_mail():
    adapter = _adapter()
    with mock.patch.object(DefaultAccountAdapter, "send_mail", return_value="sent") as parent:
        result = adapter.send_mail(UNKNOWN, "stranger@example.com", {})
    assert result == "sent"
    parent.assert_called_once()


def test_template_is_in_suppression_set():
    # Lock the exact allauth template prefix so an allauth rename can't
    # silently reopen the relay.
    assert UNKNOWN in KeelAccountAdapter.SUPPRESSED_MAIL_TEMPLATES
