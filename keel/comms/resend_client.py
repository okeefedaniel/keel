"""Resend HTTP client for keel.comms — outbound send, inbound fetch, webhook verify.

Mirrors ``keel.notifications.backends.resend_backend``: talks to ``api.resend.com``
over stdlib ``urllib`` with a browser-style User-Agent, because the official
``resend`` SDK's User-Agent gets Cloudflare-banned (HTTP 403 / error 1010) on
some Railway egress IPs. Kept dependency-free (no ``requests``, no ``svix``) so
every product that installs keel can receive comms mail without extra packages.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API_BASE = 'https://api.resend.com'
USER_AGENT = 'DockLabs-Keel/1.0 (+https://keel.docklabs.ai)'

# Svix tolerates a 5-minute clock skew on webhook timestamps (replay window).
_WEBHOOK_TOLERANCE_SECONDS = 5 * 60


class ResendError(RuntimeError):
    """Raised when the Resend API returns a non-2xx response."""


def _request(method, path_or_url, api_key, *, json_body=None, raw=False):
    url = path_or_url if path_or_url.startswith('http') else f'{API_BASE}{path_or_url}'
    data = json.dumps(json_body).encode('utf-8') if json_body is not None else None
    headers = {'Accept': 'application/json', 'User-Agent': USER_AGENT}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    if data is not None:
        headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', errors='replace')[:500]
        except Exception:
            pass
        raise ResendError(f'Resend {method} {url} -> HTTP {e.code}: {detail}') from e
    except urllib.error.URLError as e:
        raise ResendError(f'Resend {method} {url} -> {e.reason}') from e

    if raw:
        return body
    return json.loads(body) if body else {}


def send_email(api_key, payload):
    """POST /emails — returns the parsed response (includes ``id``)."""
    return _request('POST', '/emails', api_key, json_body=payload)


def get_received_email(api_key, email_id):
    """GET /emails/receiving/{id} — full inbound content.

    Returns text, html, headers, message_id, from/to/cc, received_for,
    attachments metadata, and ``raw.download_url`` (signed URL to the
    original .eml including attachment bytes).
    """
    return _request('GET', f'/emails/receiving/{email_id}', api_key)


def download_bytes(url):
    """Download a signed URL (e.g. ``raw.download_url``) — already authenticated."""
    return _request('GET', url, api_key=None, raw=True)


def verify_webhook_signature(secret, headers, body, *, now=None):
    """Verify a Svix-signed Resend webhook.

    Args:
        secret: the endpoint signing secret (``whsec_...``).
        headers: mapping providing ``svix-id``/``svix-timestamp``/``svix-signature``.
        body: the raw request body (``str`` or ``bytes``).

    Returns True only for a valid ``v1`` signature whose timestamp is within
    tolerance. Fails closed on any missing or malformed input.
    """
    if not secret:
        return False

    svix_id = headers.get('svix-id', '')
    svix_ts = headers.get('svix-timestamp', '')
    svix_sig = headers.get('svix-signature', '')
    if not (svix_id and svix_ts and svix_sig):
        return False

    try:
        ts = int(svix_ts)
    except (TypeError, ValueError):
        return False
    current = int(now if now is not None else time.time())
    if abs(current - ts) > _WEBHOOK_TOLERANCE_SECONDS:
        return False

    if isinstance(body, bytes):
        body = body.decode('utf-8')

    # whsec_ secrets carry a base64 payload after the prefix.
    key_part = secret.split('_', 1)[1] if secret.startswith('whsec_') else secret
    try:
        key = base64.b64decode(key_part)
    except Exception:
        return False

    signed_content = f'{svix_id}.{svix_ts}.{body}'.encode('utf-8')
    expected = base64.b64encode(
        hmac.new(key, signed_content, hashlib.sha256).digest()
    ).decode('utf-8')

    # The header is a space-delimited list of "<version>,<signature>".
    for part in svix_sig.split():
        version, _, signature = part.partition(',')
        if version == 'v1' and hmac.compare_digest(signature, expected):
            return True
    return False
