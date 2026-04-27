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
from django.http import JsonResponse
from django.views.decorators.http import require_GET


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
    # check_client_secret handles hashed-vs-plaintext storage transparently.
    if not app.check_client_secret(secret):
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
