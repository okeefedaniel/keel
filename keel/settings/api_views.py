"""Bearer-authenticated profile update endpoint (Keel IdP side).

``PATCH /api/v1/settings/profile/`` — updates the calling user's profile
fields on Keel's canonical KeelUser row. Auth is the user's own OIDC
access token issued by Keel; the token MUST carry the ``profile`` scope.

Called by suite-mode products after a local profile save to propagate
changes back to the IdP. Uses the user's own token so the operation is
scoped to that user — no product can update another user's profile.

Rate limit: 30/min/user. Conservative — legitimate use is one call per
user save, not a high-volume path. Anything over 30 in a minute is almost
certainly a runaway loop in a product.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW_SECONDS = 60


def _rate_limit(user_id) -> bool:
    """Return True if the request is within the per-user rate limit."""
    key = f'keel.settings.profile:rl:{user_id}'
    try:
        added = cache.add(key, 1, RATE_LIMIT_WINDOW_SECONDS)
        if added:
            return True
        count = cache.incr(key)
        return count <= RATE_LIMIT_MAX
    except Exception:
        return True  # Cache down — fail open, audit log captures everything.


def _resolve_token_user(request):
    """Return ``(user, application_id)`` for the request's bearer token.

    Validates ``Authorization: Bearer <token>`` and requires ``profile``
    scope. Returns ``(None, None)`` on any failure.
    """
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Bearer '):
        return (None, None)
    token_str = auth[7:].strip()
    if not token_str:
        return (None, None)

    try:
        from oauth2_provider.oauth2_validators import OAuth2Validator
    except ImportError:
        return (None, None)

    validator = OAuth2Validator()
    try:
        access_token = validator._load_access_token(token_str)
    except Exception:
        return (None, None)

    if access_token is None or not access_token.is_valid(['profile']):
        return (None, None)

    return (
        access_token.user,
        getattr(access_token.application, 'client_id', None),
    )


def _audit_update(user, app_id, fields_updated, request=None):
    """Write one AuditLog row for a profile sync. Best-effort."""
    try:
        from django.apps import apps as django_apps
        path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'keel_accounts.AuditLog')
        AuditLog = django_apps.get_model(path)
        AuditLog.objects.create(
            user=user,
            action='profile_update_via_sync',
            entity_type='KeelUser',
            entity_id=str(getattr(user, 'pk', '')),
            description=(
                f'Profile synced from product client_id={app_id or "unknown"}; '
                f'fields={sorted(fields_updated)}'
            ),
            changes={
                'client_id': app_id or '',
                'fields': sorted(fields_updated),
            },
            ip_address=getattr(request, 'audit_ip', None) if request else None,
        )
    except Exception:
        logger.exception('Failed to write profile_update_via_sync audit row')


@csrf_exempt
@require_http_methods(['PATCH'])
def profile_update(request):
    """Apply profile field updates from a suite-mode product.

    Accepts JSON body with any subset of:
      first_name, last_name, title, phone, timezone, locale

    Returns:
      200  {"ok": true}
      400  {"error": "..."}   (malformed request body)
      401  {"error": "..."}   (missing/invalid/expired token)
      422  {"errors": {...}}  (validation failure)
      429  {"error": "..."}   (rate limit)
    """
    user, app_id = _resolve_token_user(request)
    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    if not _rate_limit(user.pk):
        logger.warning('settings.profile.sync: rate limit hit for user=%s', user.pk)
        return JsonResponse({'error': 'Rate limit exceeded'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({'error': 'Expected a JSON object'}, status=400)

    # Validate via ProfileForm — reuses the same field rules as the UI.
    from keel.accounts.forms import ProfileForm
    allowed_fields = {'first_name', 'last_name', 'title', 'phone', 'timezone', 'locale'}
    data = {k: v for k, v in body.items() if k in allowed_fields}

    # ProfileForm expects all its fields to be present (even if unchanged)
    # since it's a ModelForm. Merge with current instance data so missing
    # keys don't accidentally blank existing values.
    current = {
        field: getattr(user, field, '') or ''
        for field in allowed_fields
    }
    current.update(data)

    form = ProfileForm(current, instance=user)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=422)

    form.save()
    _audit_update(user, app_id, list(data.keys()), request)
    logger.info(
        'settings.profile.sync.ok: user=%s updated fields=%s via client=%s',
        user.pk, sorted(data.keys()), app_id or 'unknown',
    )
    return JsonResponse({'ok': True})
