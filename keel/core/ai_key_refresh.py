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

Design — a token-independent service lookup
-------------------------------------------

Presence is read live from Keel's ``GET /oauth/ai-key-status/?sub=<sub>``
endpoint, authenticated with the **product's own OIDC client credentials**
(HTTP Basic) — the same peer-client auth ``SessionFreshnessMiddleware`` uses
for ``/oauth/session-status/``. Crucially this does **not** depend on the
user having a stored OIDC access token: most products run allauth's default
``SOCIALACCOUNT_STORE_TOKENS=False`` and hold no ``SocialToken`` rows, which
is why the earlier access-token-based cross-product fetch couldn't self-heal
the claim. The ``sub`` is the user's ``SocialAccount.uid`` (the KeelUser pk),
which is present regardless of token storage. Only a boolean crosses the
wire — never the key.

The request goes through the shared ``keel.core.ai.issuer_safe_for_secret``
guard (HTTPS-only outside DEBUG, issuer-host allowlist) and a redirect-
refusing opener, so the product's client secret can't leak to a misconfigured
or hostile issuer.

Contract
--------

``refresh_ai_key_claim(user)`` is:

- **Corrective-only.** It flips a stale ``False`` claim to ``True`` when Keel
  confirms the key exists; it never writes ``False``. A negative or failed
  lookup leaves the stored claim exactly as it was — so it can never
  introduce a false negative and never makes the gate more permissive on
  error.
- **Targeted & bounded.** The caller (``AIKeyClaimRefreshMiddleware``) only
  invokes it for users in the ``needs_key`` state, at most once per session
  TTL. A user who already has a key never triggers a lookup.
- **Best-effort.** Every failure path returns ``None`` and leaves the stored
  claim untouched. It never raises into the request.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

# How long a single session trusts its last check before re-verifying.
AI_KEY_REFRESH_TTL = 600  # seconds (10 minutes)

_HTTP_TIMEOUT = 5  # seconds


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


def _query_ai_key_present(issuer: str, sub: str) -> bool | None:
    """Poll Keel's ai-key-status endpoint for this sub.

    Returns ``True``/``False`` on a clean answer, or ``None`` on any skip or
    failure (missing client creds, unsafe issuer, network/parse error).
    Never raises.
    """
    from keel.core.ai import _build_no_redirect_opener, issuer_safe_for_secret

    if not issuer_safe_for_secret(issuer):
        return None
    client_id = getattr(django_settings, 'KEEL_OIDC_CLIENT_ID', '') or ''
    client_secret = getattr(django_settings, 'KEEL_OIDC_CLIENT_SECRET', '') or ''
    if not (client_id and client_secret):
        return None

    basic = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
    url = f'{issuer}/oauth/ai-key-status/?' + urllib.parse.urlencode({'sub': sub})
    req = urllib.request.Request(
        url,
        headers={'Authorization': f'Basic {basic}', 'Accept': 'application/json'},
    )
    try:
        opener = _build_no_redirect_opener()
        with opener.open(req, timeout=_HTTP_TIMEOUT) as resp:
            if not (200 <= resp.status < 300):
                return None
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        logger.info('ai_key_refresh.query: HTTP %s', exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.info('ai_key_refresh.query: %s', exc)
        return None

    val = data.get('ai_key_present')
    return val if isinstance(val, bool) else None


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
    issuer = (getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or '').rstrip('/')
    if not issuer:
        return None  # Not a suite deployment — nothing to refresh against.

    account = _keel_social_account(user)
    if account is None or not getattr(account, 'uid', ''):
        return None

    present = _query_ai_key_present(issuer, account.uid)
    if present is not True:
        # False (no key) or None (unknown/error). Corrective-only: never
        # write a False here — leave the stored claim as-is.
        return None

    try:
        _store_claim_true(account)
    except Exception as exc:  # noqa: BLE001
        logger.info('ai_key_refresh.store: %s', exc)
        return None
    logger.info('ai_key_refresh.ok: user=%s corrected stale ai_key_present claim', user.pk)
    return True
