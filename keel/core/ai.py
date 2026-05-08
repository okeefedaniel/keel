"""Shared Claude AI client wrapper for DockLabs products.

Provides thin helpers around the Anthropic SDK so products don't duplicate
client initialization, JSON response parsing, and error handling.

Products keep their own prompts and domain logic — this module handles
the plumbing.

Usage:
    from keel.core.ai import get_client, call_claude, parse_json_response

    # Simple call
    client = get_client()
    response = call_claude(
        client,
        system='You are a helpful assistant.',
        user_message='Summarize this document.',
    )

    # JSON-returning call
    data = parse_json_response(response)
    # data is a dict, or None on parse failure

Configuration:
    ANTHROPIC_API_KEY — required (in settings or env)
    KEEL_AI_MODEL — optional, defaults to 'claude-sonnet-4-20250514'
    KEEL_AI_MAX_TOKENS — optional, defaults to 500
"""
import json
import logging
import os
import re

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'claude-sonnet-4-20250514'
DEFAULT_MAX_TOKENS = 500


def get_client(api_key=None):
    """Return an Anthropic client instance.

    Resolves API key from (in order):
    1. Explicit ``api_key`` parameter
    2. ``settings.ANTHROPIC_API_KEY``
    3. ``ANTHROPIC_API_KEY`` environment variable

    Returns None if anthropic is not installed or no key is found.

    .. note::
        Prefer ``get_client_for_user`` over this when the call is made
        on behalf of a logged-in user — that path enforces the three-
        layer AI gate and bills the user's own Anthropic account
        instead of the deployment-wide key.
    """
    try:
        import anthropic
    except ImportError:
        logger.error('anthropic package not installed — pip install anthropic')
        return None

    key = (
        api_key
        or getattr(settings, 'ANTHROPIC_API_KEY', None)
        or os.environ.get('ANTHROPIC_API_KEY')
    )
    if not key:
        logger.error('No Anthropic API key found')
        return None

    # Surface every legacy fallback at WARN so consumer-product
    # refactors that accidentally drop the user (background tasks,
    # signal handlers, missed wiring) are detectable in app logs
    # before they show up on the DockLabs Anthropic bill. Skip the
    # warn when an explicit key was passed (caller knows what
    # they're doing) or when the deployment opts out via
    # ``KEEL_AI_QUIET_DEPLOYMENT_FALLBACK=True``.
    if api_key is None and not getattr(
        settings, 'KEEL_AI_QUIET_DEPLOYMENT_FALLBACK', False,
    ):
        logger.warning(
            'get_client() resolved key from deployment-wide ANTHROPIC_API_KEY '
            '— this bills DockLabs, not the user. Prefer get_client_for_user(user, request=request) '
            'for user-attributed AI calls. Set KEEL_AI_QUIET_DEPLOYMENT_FALLBACK=True to suppress.'
        )
    return anthropic.Anthropic(api_key=key)


def get_client_for_user(user, product_code=None, *, request=None):
    """Return an Anthropic client keyed to the user's stored API key.

    Enforces the three-layer AI gate (org sub, per-user access, key
    presence). Returns None whenever the user can't actually call
    Anthropic — callers should treat None as "feature not available,
    render the appropriate fallback UI" and NEVER fall through to a
    deployment-wide key. The whole point of this function is that AI
    usage bills the user's own Anthropic account.

    Resolution order for the cleartext key:

    1. **Local field** — if ``user.anthropic_api_key_encrypted`` has a
       value, decrypt and use it. This is the suite-mode IdP (Keel)
       and standalone-mode (product) path.

    2. **Cross-product fetch** — if the local field is empty AND the
       deployment is in suite mode AND the request has the user's
       OIDC SocialToken, fetch the key from Keel's
       ``GET /api/v1/ai/key/`` endpoint using the user's access token.
       The fetched key is cached on the request object for the
       request lifetime so a single page render makes one Keel hop
       even if the AI surface is invoked multiple times.

    Pass ``request=request`` from the calling view if you want the
    cross-product fetch to work — without a request the function can
    only resolve the local field.
    """
    from keel.core.ai_access import user_can_use_ai

    if user is None or not getattr(user, 'is_authenticated', False):
        return None

    if not user_can_use_ai(user, product_code):
        return None

    try:
        import anthropic
    except ImportError:
        logger.error('anthropic package not installed — pip install anthropic')
        return None

    key = _resolve_user_key(user, request=request)
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def _resolve_user_key(user, *, request=None):
    """Return the cleartext key, fetching from Keel in suite mode."""
    # Local field first — wins on Keel itself and on standalone-mode
    # products with a local profile.
    local = getattr(user, 'anthropic_api_key', '') or ''
    if local:
        return local

    # Suite mode: fetch from Keel. Cache on the request so multiple
    # AI calls in one render don't each cross the network.
    if request is None:
        return ''
    cached = getattr(request, '_sensitive_keel_ai_key', None)
    if cached is not None:
        return cached or ''
    fetched = _fetch_key_from_keel(user, request) or ''
    try:
        request._sensitive_keel_ai_key = fetched
    except Exception:
        pass
    return fetched


def _build_no_redirect_opener():
    """Return a urllib opener that refuses to follow redirects.

    Default ``urllib`` follows 30x redirects and persists the
    ``Authorization`` header across hops. If ``KEEL_OIDC_ISSUER`` ever
    points at a host that bounces (compromised DNS, misconfigured
    front door), the user's full OIDC access token would leak to the
    redirect target. Refusing redirects closes that path entirely.
    """
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(
                req.get_full_url(), code,
                f'redirect to {newurl} blocked — keel.ai.key never follows redirects',
                headers, fp,
            )

    return urllib.request.build_opener(_NoRedirect())


def _fetch_key_from_keel(user, request):
    """Call Keel's ``/api/v1/ai/key/`` with the user's bearer token.

    Returns cleartext on success, empty string on any failure. Logs
    failures at WARNING level so a misconfigured product is detectable
    in app logs without crashing the AI surface.

    Security guards:

    - **HTTPS required outside DEBUG.** ``KEEL_OIDC_ISSUER`` must start
      with ``https://`` (or be a localhost dev URL); otherwise the
      bearer token would transit cleartext. Refuse the call, log an
      error so misconfiguration is loud, and let the AI surface fall
      back to the needs-key state.
    - **No redirects.** ``urllib`` follows 30x by default and persists
      the ``Authorization`` header. We install a redirect handler that
      raises so a compromised DNS / misconfigured front door cannot
      bounce the request to an attacker host with the token attached.
    """
    issuer = (
        getattr(settings, 'KEEL_OIDC_ISSUER', '') or ''
    ).rstrip('/')
    if not issuer:
        return ''

    # Scheme allowlist — prod must be HTTPS. The localhost carve-out
    # keeps dev workflows working without forcing TLS on every machine;
    # DEBUG=True also unlocks plain http for local Keel test instances.
    is_local = issuer.startswith('http://localhost') or issuer.startswith('http://127.0.0.1')
    if not issuer.startswith('https://') and not (
        getattr(settings, 'DEBUG', False) or is_local
    ):
        logger.error(
            'KEEL_OIDC_ISSUER must use https:// in production — refusing '
            "to send bearer token over plaintext to %r", issuer,
        )
        return ''

    # Host allowlist — defense against env-var corruption / typo
    # attacks. ``KEEL_AI_KEY_FETCH_HOSTS`` is a comma-separated
    # allowlist of acceptable issuer hosts. Default permits the
    # canonical DockLabs domain plus localhost for dev; a deployment
    # using a different host MUST opt in via setting. Without this,
    # a typo'd ``KEEL_OIDC_ISSUER=https://attaker.com`` (or env-var
    # injection) would ship the user's bearer token there.
    from urllib.parse import urlparse
    issuer_host = urlparse(issuer).hostname or ''
    default_hosts = {
        'keel.docklabs.ai', 'demo-keel.docklabs.ai',
        'localhost', '127.0.0.1',
    }
    allowed_hosts = set(
        (getattr(settings, 'KEEL_AI_KEY_FETCH_HOSTS', '') or '')
        .replace(' ', '').split(',')
    ) - {''} or default_hosts
    if issuer_host not in allowed_hosts and not (
        getattr(settings, 'DEBUG', False) or is_local
    ):
        logger.error(
            'KEEL_OIDC_ISSUER host %r not in allowlist %r — refusing '
            'to send bearer token. Set KEEL_AI_KEY_FETCH_HOSTS to '
            'override.', issuer_host, sorted(allowed_hosts),
        )
        return ''

    token = _user_access_token(user)
    if not token:
        return ''

    try:
        import json as _json
        import urllib.error
        import urllib.request

        opener = _build_no_redirect_opener()
        req = urllib.request.Request(
            f'{issuer}/api/v1/ai/key/',
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
            },
        )
        with opener.open(req, timeout=5) as resp:
            payload = _json.loads(resp.read().decode())
        return payload.get('key', '') or ''
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # No key configured — expected, render needs-key prompt.
            return ''
        logger.warning('keel.ai.key fetch failed: status=%s', exc.code)
        return ''
    except Exception:
        logger.exception('keel.ai.key fetch failed')
        return ''


def _user_access_token(user):
    """Return the user's current OIDC access token, or empty string.

    Reads from allauth's ``SocialToken`` table when present. allauth
    is optional on the product side — without it (e.g. on Keel
    itself, where the user is on the IdP), this returns empty and
    the caller falls back to the local-field path.
    """
    try:
        from allauth.socialaccount.models import SocialToken
    except ImportError:
        return ''
    try:
        st = (
            SocialToken.objects
            .filter(account__user=user, account__provider='keel')
            .order_by('-id')
            .first()
        )
    except Exception:
        return ''
    return getattr(st, 'token', '') if st else ''


def call_claude(client, system, user_message, model=None, max_tokens=None):
    """Make a standard Claude API call and return the text response.

    Args:
        client: Anthropic client from ``get_client()``.
        system: System prompt string.
        user_message: User message string.
        model: Model ID (defaults to KEEL_AI_MODEL setting or claude-sonnet-4-20250514).
        max_tokens: Max tokens (defaults to KEEL_AI_MAX_TOKENS setting or 500).

    Returns:
        Response text string, or None on error.
    """
    if client is None:
        return None

    model = model or getattr(settings, 'KEEL_AI_MODEL', DEFAULT_MODEL)
    max_tokens = max_tokens or getattr(settings, 'KEEL_AI_MAX_TOKENS', DEFAULT_MAX_TOKENS)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{'role': 'user', 'content': user_message}],
        )
        return response.content[0].text
    except Exception:
        logger.exception('Claude API call failed')
        return None


def parse_json_response(text):
    """Parse a JSON response from Claude, stripping markdown fences if present.

    Handles common patterns:
    - Raw JSON
    - ```json ... ``` fenced blocks
    - ``` ... ``` fenced blocks

    Returns:
        Parsed dict/list, or None on failure.
    """
    if not text:
        return None

    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning('Failed to parse JSON from Claude response: %s', text[:200])
        return None
