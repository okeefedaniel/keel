"""Keel-side OIDC endpoints beyond what django-oauth-toolkit ships.

Currently:

- ``session_status`` — peer products call this to find out when a given
  user (identified by their ``sub`` claim, which is the KeelUser pk)
  last logged out of the suite via ``/suite/logout/``. Used by
  ``keel.accounts.middleware.SessionFreshnessMiddleware`` to invalidate
  stale per-product Django sessions when the user has logged out at
  Keel from another tab.
"""
import base64

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def _verify_client_secret(provided, stored):
    """Compare provided secret against stored value (hashed or plaintext)."""
    from django.contrib.auth.hashers import check_password, identify_hasher
    from django.utils.crypto import constant_time_compare
    try:
        identify_hasher(stored)
        return check_password(provided, stored)
    except ValueError:
        return constant_time_compare(provided, stored)


def _authenticate_peer_client(request):
    """Validate HTTP Basic credentials against a registered OIDC client.

    Any confidential ``oauth2_provider.Application`` may call this
    endpoint — every DockLabs product is already a registered client
    with its own ``client_id`` / ``client_secret``, so no new credential
    has to be provisioned.
    """
    from oauth2_provider.models import Application

    header = request.META.get('HTTP_AUTHORIZATION', '')
    if not header.startswith('Basic '):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return None
    client_id, sep, secret = decoded.partition(':')
    if not sep:
        return None
    app = Application.objects.filter(
        client_id=client_id,
        client_type=Application.CLIENT_CONFIDENTIAL,
    ).first()
    if app is None:
        return None
    if not _verify_client_secret(secret, app.client_secret):
        return None
    return app


@require_GET
def session_status(request):
    """Return the user's suite-wide logout epoch, if any.

    ``GET /oauth/session-status/?sub=<keel_user_pk>``

    Response (200)::

        {"sub": "<uuid>", "last_logout_at": "2026-04-27T15:32:11.123456+00:00" | null}

    A 200 with ``last_logout_at: null`` is returned for unknown subs as
    well as for known users who have never logged out — the consumer
    middleware treats both identically (no-op), so collapsing them
    avoids leaking which subs exist at Keel.

    401 if the caller doesn't present valid client credentials. 400 if
    ``sub`` is missing.
    """
    if _authenticate_peer_client(request) is None:
        return JsonResponse({'detail': 'unauthorized'}, status=401)

    sub = request.GET.get('sub', '').strip()
    if not sub:
        return JsonResponse({'detail': 'sub query param required'}, status=400)

    User = get_user_model()
    last_logout_at = (
        User.objects.filter(pk=sub)
        .values_list('last_logout_at', flat=True)
        .first()
    )
    return JsonResponse({
        'sub': sub,
        'last_logout_at': last_logout_at.isoformat() if last_logout_at else None,
    })


@require_GET
def ai_key_status(request):
    """Report whether a user has an Anthropic key set at Keel.

    ``GET /oauth/ai-key-status/?sub=<keel_user_pk>``

    Response (200)::

        {"sub": "<uuid>", "ai_key_present": true | false}

    This is the live source of truth behind the AI gate's ``needs_key``
    prompt. Products stamp ``ai_key_present`` into the user's OIDC claim
    at login, but that snapshot goes stale if the user sets their key on
    Keel mid-session. ``keel.accounts.middleware.AIKeyClaimRefreshMiddleware``
    polls this endpoint to self-heal the stale claim — token-independent,
    so it works even where the product doesn't persist OIDC access tokens
    (``SOCIALACCOUNT_STORE_TOKENS=False``, the allauth default).

    Auth is the same peer-client HTTP Basic as ``session_status`` — every
    product is already a registered confidential OIDC client, so no new
    credential is provisioned. Only a boolean is returned (never the key).

    An unknown sub returns ``ai_key_present: false`` (a 200, not a 404) so
    the endpoint doesn't leak which subs exist at Keel — the consumer
    treats "no key" and "no such user" identically (leave the claim as-is).

    401 without valid client credentials. 400 if ``sub`` is missing.
    """
    if _authenticate_peer_client(request) is None:
        return JsonResponse({'detail': 'unauthorized'}, status=401)

    sub = request.GET.get('sub', '').strip()
    if not sub:
        return JsonResponse({'detail': 'sub query param required'}, status=400)

    User = get_user_model()
    try:
        user = User.objects.filter(pk=sub).first()
    except (ValueError, ValidationError):
        # Malformed sub (e.g. not a valid UUID) — treat as unknown.
        user = None
    present = bool(user and user.has_anthropic_key())
    return JsonResponse({'sub': sub, 'ai_key_present': present})
