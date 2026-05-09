"""Best-effort profile sync from a suite-mode product back to Keel IdP.

Called after a successful local profile save. Uses the user's own OIDC
access token (from allauth's SocialToken table) so the call is scoped to
that user — no shared service credential can impersonate other users.

Failure modes are all silent from the user's perspective:
  - No token (standalone deploy, or user hasn't OIDC-logged in yet): skip
  - Token expired (>1h since last OIDC login): log + skip
  - Network / 5xx from Keel: log + skip
  - 401 (scope missing or token revoked): log + skip

The user always sees "Profile saved." The propagation copy in the template
sets expectations: "Changes appear in other DockLabs products the next
time you sign in to each one."
"""
import logging
import urllib.request
import urllib.error
import json

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)


def _get_social_token(user):
    """Return the allauth SocialToken for the keel provider, or None."""
    try:
        from allauth.socialaccount.models import SocialToken
    except ImportError:
        return None
    try:
        return (
            SocialToken.objects
            .filter(account__user=user, account__provider='keel')
            .order_by('-id')
            .select_related('account')
            .first()
        )
    except Exception:
        return None


def _token_is_expired(social_token) -> bool:
    """Return True if the token's expires_at is in the past."""
    import datetime
    expires_at = getattr(social_token, 'expires_at', None)
    if expires_at is None:
        return False  # No expiry info — optimistically attempt the call.
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    # Make expires_at tz-aware if it isn't already.
    if expires_at.tzinfo is None:
        import django.utils.timezone as tz
        expires_at = tz.make_aware(expires_at)
    return now >= expires_at


def sync_profile_to_keel(user, data: dict) -> bool:
    """PATCH the user's profile on Keel IdP using their own OIDC token.

    Args:
        user: The KeelUser whose profile was just saved locally.
        data: Cleaned form data dict (keys: first_name, last_name, title,
              phone, timezone, locale — all optional).

    Returns:
        True on success, False on any skip or error.

    Never raises.
    """
    issuer = getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or ''
    issuer = issuer.rstrip('/')
    if not issuer:
        return False  # Not a suite deployment — nothing to sync.

    st = _get_social_token(user)
    if not st:
        logger.debug('settings.profile.sync: no SocialToken for user=%s — skipping', user.pk)
        return False

    if _token_is_expired(st):
        logger.warning(
            'settings.profile.sync.token_expired: user=%s token expired, '
            'profile change is local-only until re-login',
            user.pk,
        )
        return False

    token = getattr(st, 'token', '') or ''
    if not token:
        logger.debug('settings.profile.sync: empty token for user=%s — skipping', user.pk)
        return False

    # Build payload: only include fields present in the form data.
    allowed_fields = {'first_name', 'last_name', 'title', 'phone', 'timezone', 'locale'}
    payload = {k: v for k, v in data.items() if k in allowed_fields}
    if not payload:
        return True  # Nothing to sync (edge case: empty form submission).

    url = f'{issuer}/api/v1/settings/profile/'
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        method='PATCH',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        if status == 401:
            logger.warning(
                'settings.profile.sync.unauthorized: user=%s HTTP 401 — '
                'token may be expired or missing profile scope',
                user.pk,
            )
        elif status >= 500:
            logger.error(
                'settings.profile.sync.server_error: user=%s HTTP %s from Keel IdP',
                user.pk, status,
            )
        else:
            logger.warning(
                'settings.profile.sync: user=%s unexpected HTTP %s', user.pk, status,
            )
        return False
    except Exception as exc:
        logger.warning('settings.profile.sync: user=%s network error: %s', user.pk, exc)
        return False

    if 200 <= status < 300:
        logger.info('settings.profile.sync.ok: user=%s synced to Keel IdP', user.pk)
        return True

    logger.warning('settings.profile.sync: user=%s unexpected status %s', user.pk, status)
    return False
