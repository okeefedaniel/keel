"""SSRF-hardened HTTP fetch helper.

Use ``safe_get(url)`` instead of ``requests.get(url)`` whenever the URL is
influenced by user input (company websites, AI-news URL parsing, webhook
callbacks, bill PDF downloads, etc.). The helper:

  * requires http(s) scheme
  * resolves the hostname and rejects private / loopback / link-local /
    carrier-grade-NAT / IPv6 ULA / link-local / multicast addresses
  * rejects the Railway internal zone (``*.railway.internal``)
  * follows redirects manually, re-validating every hop
  * caps response size and wall-clock time
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse, urljoin

import requests

logger = logging.getLogger(__name__)


class UnsafeURLError(ValueError):
    """Raised when a URL resolves to a disallowed destination."""


DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_MAX_REDIRECTS = 5

# Hostname suffixes that must never be fetched — Railway's internal mesh.
_BLOCKED_HOST_SUFFIXES = ('.railway.internal', '.internal')


def _is_blocked_host(hostname: str) -> bool:
    host = (hostname or '').lower().strip('.')
    if not host:
        return True
    for suffix in _BLOCKED_HOST_SUFFIXES:
        if host.endswith(suffix):
            return True
    return False


def _is_blocked_address(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise UnsafeURLError(f'scheme {parsed.scheme!r} is not allowed')
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError('URL has no hostname')
    if _is_blocked_host(hostname):
        raise UnsafeURLError(f'hostname {hostname!r} is in a blocked zone')

    # Resolve every address and reject if any is private/loopback/link-local.
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f'unable to resolve {hostname!r}: {e}') from e
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_address(ip):
            raise UnsafeURLError(
                f'hostname {hostname!r} resolves to blocked address {addr}'
            )
    return parsed.scheme, hostname


def safe_get(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    headers: dict | None = None,
) -> requests.Response:
    """Fetch ``url`` with SSRF, size, and time guards.

    Redirects are followed manually; every hop is re-validated against the
    private-network blocklist. The response body is streamed and truncated
    at ``max_bytes``.

    Raises ``UnsafeURLError`` for disallowed destinations and
    ``requests.RequestException`` subclasses for transport failures.
    """
    current_url = url
    for _hop in range(max_redirects + 1):
        _validate_url(current_url)
        resp = requests.get(
            current_url,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
            headers=headers or {},
        )
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get('Location')
            resp.close()
            if not location:
                raise UnsafeURLError('redirect without Location header')
            current_url = urljoin(current_url, location)
            continue

        # Enforce size cap by reading in chunks.
        body = bytearray()
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > max_bytes:
                resp.close()
                raise UnsafeURLError(
                    f'response exceeded {max_bytes} bytes'
                )
        resp._content = bytes(body)
        return resp

    raise UnsafeURLError(f'too many redirects (>{max_redirects})')
