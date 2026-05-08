"""Bearer-authenticated endpoints for AI key handoff.

``GET /api/v1/ai/key/`` — returns the calling user's plaintext
Anthropic key. Auth is the user's OIDC access token (issued by Keel
itself); the token MUST carry the ``ai`` scope.

Audit-log policy: every fetch writes one ``AuditLog`` row with
action='ai_key_fetch'. The plaintext key is NEVER logged; only the
last-4 hint and the calling client/application id are recorded so
ops can spot anomalous fetch patterns.

Rate limit: 60/min/user. Tighter than the suite default because the
plaintext key is being handed out — a runaway product loop should be
visible quickly. The throttle key is the user pk (not IP) so a
shared egress IP across products doesn't conflate users.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

# Rate-limit: max fetches per user per window. Conservative because
# every fetch is a deliberate cross-product call — anything past this
# is almost certainly a bug.
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW_SECONDS = 60


def _rate_limit(user_id) -> bool:
    """Return True if the request is within the per-user rate limit."""
    key = f'keel.ai.key:rl:{user_id}'
    try:
        # cache.incr() raises if missing; set+incr is the standard idiom.
        added = cache.add(key, 1, RATE_LIMIT_WINDOW_SECONDS)
        if added:
            return True
        count = cache.incr(key)
        return count <= RATE_LIMIT_MAX
    except Exception:
        # Cache misconfigured / down — fail OPEN. The audit log still
        # captures every fetch, so a runaway loop is detectable post-
        # hoc; failing closed would break AI in every product on a
        # cache outage.
        return True


def _resolve_token_user(request):
    """Return ``(user, application_id)`` for the request's bearer token.

    Validates ``Authorization: Bearer <token>`` via django-oauth-toolkit's
    canonical helper (``OAuth2Validator._load_access_token``), which
    looks up against the indexed ``token_checksum`` column rather than
    the unindexed plaintext ``token`` column. ``AccessToken.is_valid(scopes)``
    composes the not-expired + scope-allowlist checks in one call.

    Returns ``(None, None)`` on any failure so the caller can return
    401 without leaking which check failed.
    """
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Bearer '):
        return (None, None)
    token_str = auth[7:].strip()
    if not token_str:
        return (None, None)

    try:
        from oauth2_provider.oauth2_validators import OAuth2Validator
    except ImportError:  # pragma: no cover — Keel always has it
        return (None, None)

    validator = OAuth2Validator()
    try:
        access_token = validator._load_access_token(token_str)
    except Exception:  # noqa: BLE001 — defensive against library churn
        return (None, None)

    # is_valid(scopes) checks: token is not None, has not expired, and
    # the requested scope set is a subset of the token's scopes. Returns
    # False on any failure — no exception. The required scope is ``ai``.
    if access_token is None or not access_token.is_valid(['ai']):
        return (None, None)

    return (
        access_token.user,
        getattr(access_token.application, 'client_id', None),
    )


def _audit_fetch(user, app_id, success, hint='', request=None):
    """Write one ``AuditLog`` row for an /ai/key/ fetch.

    Best-effort: an audit-log failure does NOT block the key handoff.
    The fetch is still observable via app logs; the audit row is the
    canonical trail for compliance review.

    Records the calling IP (``request.audit_ip`` set by the
    ``AuditMiddleware``) so ops can spot anomalous egress patterns —
    a stolen bearer token shipped from an unexpected host shows up as
    an IP delta in the audit stream. Without this, the strongest
    mitigating control on the BYO-key model is blind to source.
    """
    try:
        from django.apps import apps as django_apps
        path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'keel_accounts.AuditLog')
        AuditLog = django_apps.get_model(path)
        AuditLog.objects.create(
            user=user,
            action='ai_key_fetch',
            entity_type='AnthropicAPIKey',
            entity_id=str(getattr(user, 'pk', '')),
            description=(
                f'AI key fetched by client_id={app_id or "unknown"}; '
                f'success={success}; hint={hint}'
            ),
            changes={
                'client_id': app_id or '',
                'success': bool(success),
                'hint': hint,
            },
            ip_address=getattr(request, 'audit_ip', None) if request else None,
        )
    except Exception:
        logger.exception('Failed to write ai_key_fetch audit row')


@csrf_exempt
@require_GET
def ai_key_view(request):
    """Return ``{key, expires_in, hint}`` for the calling user.

    Status codes:
    - ``200`` — key available, returned in body.
    - ``401`` — bearer token missing/invalid/expired/wrong scope.
    - ``404`` — token valid but the user has no key set. Products
      should treat this as "render needs-key prompt".
    - ``429`` — per-user rate limit tripped.
    """
    user, app_id = _resolve_token_user(request)
    if user is None or not getattr(user, 'is_authenticated', False):
        return JsonResponse({'error': 'invalid_token'}, status=401)

    if not _rate_limit(user.pk):
        _audit_fetch(user, app_id, success=False, hint='rate_limited', request=request)
        return JsonResponse({'error': 'rate_limited'}, status=429)

    if not getattr(user, 'has_anthropic_key', lambda: False)():
        _audit_fetch(user, app_id, success=False, hint='no_key', request=request)
        return JsonResponse({'error': 'no_key_configured'}, status=404)

    key = user.anthropic_api_key
    hint = user.anthropic_key_hint() if hasattr(user, 'anthropic_key_hint') else ''
    _audit_fetch(user, app_id, success=True, hint=hint, request=request)

    # Cache-Control: never store. The endpoint returns plaintext
    # credentials — every cache layer (browser, CDN, intermediary)
    # MUST treat each fetch as fresh. Belt-and-suspenders alongside
    # the bearer-only auth model.
    response = JsonResponse({
        'key': key,
        'expires_in': 60,  # advisory: products should refetch hourly
        'hint': hint,
        'fetched_at': timezone.now().isoformat(),
    })
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    return response
