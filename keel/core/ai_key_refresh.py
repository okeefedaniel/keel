"""Best-effort self-healing refresh of the ``ai_key_present`` OIDC claim.

The problem this solves
-----------------------

``ai_key_present`` is a *login-time snapshot* stamped into the user's
``SocialAccount.extra_data`` by the OIDC adapter (see ``keel.core.sso``).
The AI gate (`keel.core.ai_access`) reads it to decide whether to show the
"you have not yet put in your API key" prompt and whether AI features are
usable.

When a user sets their Anthropic key on Keel **after** logging into a
product, nothing refreshes that snapshot mid-session: the product keeps
showing the "needs key" prompt (and keeps AI disabled) until the user's next
full OIDC login, even though the key now exists. Users reasonably read that
as "I already added my key — why is it still asking?".

This module re-checks the claim out-of-band and rewrites the snapshot when
it has gone stale.

Design — delegate the network hop to the hardened fetch
-------------------------------------------------------

Presence is derived from ``keel.core.ai._fetch_key_from_keel`` — the same
security-hardened call the AI features already use to pull the user's key
from Keel (HTTPS-only outside DEBUG, issuer-host allowlist, redirect-refusing
opener; see the CSO guards on that function). We deliberately do **not** open
a second, differently-guarded network path to Keel here, and we do **not**
mint fresh tokens: this rides the user's existing OIDC access token exactly
as the feature path does. The cleartext key it returns is used only to
compute a boolean and is never stored.

Contract
--------

``refresh_ai_key_claim(user)`` is:

- **Corrective-only.** It can flip a stale ``False`` claim to ``True`` when
  Keel confirms the key exists; it never writes ``False``. A negative or
  failed fetch (no key, or an expired access token) leaves the stored claim
  exactly as it was — so it can never introduce a false negative and never
  makes the gate *more* permissive on error.
- **Targeted & bounded.** The caller (``AIKeyClaimRefreshMiddleware``) only
  invokes it for users already in the ``needs_key`` state, at most once per
  session TTL. A user who already has a key never triggers a fetch.
- **Best-effort.** Every failure path returns ``None`` and leaves the stored
  claim untouched. It never raises into the request.

Residual limitation: a user whose OIDC access token has expired (past the
~1h access-token lifetime, with no valid token on the product side) won't
self-heal until their next login — the hardened fetch has no key to present.
That's a strict improvement over the login-time-only behavior and avoids
introducing refresh-token machinery the suite otherwise doesn't run.
"""
from __future__ import annotations

import logging

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

# How long a single session trusts its last check before re-verifying.
AI_KEY_REFRESH_TTL = 600  # seconds (10 minutes)


def _keel_social_account(user):
    """Return the user's keel-provider SocialAccount, or None."""
    try:
        from allauth.socialaccount.models import SocialAccount
    except ImportError:
        return None
    try:
        return SocialAccount.objects.filter(user=user, provider='keel').first()
    except Exception:  # noqa: BLE001 — defensive against schema drift
        return None


def _store_claim_true(account) -> None:
    """Rewrite the ai_key_present snapshot in SocialAccount.extra_data to True.

    ``_oidc_ai_key_present`` reads ``userinfo.ai_key_present`` first and the
    top level as a fallback, so we set both.
    """
    data = account.extra_data if isinstance(account.extra_data, dict) else {}
    userinfo = data.get('userinfo')
    if not isinstance(userinfo, dict):
        userinfo = {}
    userinfo['ai_key_present'] = True
    data['userinfo'] = userinfo
    data['ai_key_present'] = True
    account.extra_data = data
    account.save(update_fields=['extra_data'])


def refresh_ai_key_claim(user) -> bool | None:
    """Re-check the user's Anthropic-key status against Keel and, if the key
    exists, correct a stale ``ai_key_present=False`` claim to ``True``.

    Returns ``True`` when it confirmed a key and updated the claim, else
    ``None`` (no key confirmed, or skipped/failed — claim left untouched).
    Never raises.
    """
    issuer = (getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or '').strip()
    if not issuer:
        return None  # Not a suite deployment — nothing to refresh against.

    account = _keel_social_account(user)
    if account is None:
        return None

    # Reuse the hardened cross-product fetch. It returns the cleartext key on
    # success or '' on any failure (no key / expired token / network error).
    # We use only its truthiness and never persist the cleartext.
    try:
        from keel.core.ai import _fetch_key_from_keel
        key = _fetch_key_from_keel(user, None)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.info('ai_key_refresh.fetch: %s', exc)
        return None

    if not key:
        # No key confirmed (genuinely absent, or token too stale to fetch).
        # Corrective-only: never write a False here.
        return None

    try:
        _store_claim_true(account)
    except Exception as exc:  # noqa: BLE001
        logger.info('ai_key_refresh.store: %s', exc)
        return None
    logger.info('ai_key_refresh.ok: user=%s corrected stale ai_key_present claim', user.pk)
    return True
