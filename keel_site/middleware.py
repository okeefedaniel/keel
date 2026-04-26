"""Keel site middleware."""
from urllib.parse import urlparse

from django.conf import settings


_DEFAULT_ORIGIN = 'https://keel.docklabs.ai'


class APICorsMiddleware:
    """Add CORS headers to /api/ endpoints only.

    This allows DockLabs products (beacon.docklabs.ai, harbor.docklabs.ai, etc.)
    to POST change requests to keel.docklabs.ai/api/requests/ingest/.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Handle preflight OPTIONS requests for API paths
        if request.method == 'OPTIONS' and request.path.startswith('/api/'):
            from django.http import HttpResponse
            response = HttpResponse()
            response['Access-Control-Allow-Origin'] = self._get_origin(request)
            response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response['Access-Control-Max-Age'] = '86400'
            return response

        response = self.get_response(request)

        # Add CORS headers to API responses
        if request.path.startswith('/api/'):
            response['Access-Control-Allow-Origin'] = self._get_origin(request)
            response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

        return response

    def _get_origin(self, request):
        """Return the requesting origin if it's a DockLabs domain.

        Uses parsed-host comparison (NOT substring) so origins like
        ``https://attackerdocklabs.ai`` and ``https://docklabs.ai.evil``
        cannot be reflected into ``Access-Control-Allow-Origin``.
        """
        origin = request.META.get('HTTP_ORIGIN', '')
        if not origin:
            return _DEFAULT_ORIGIN
        try:
            parsed = urlparse(origin)
        except Exception:
            return _DEFAULT_ORIGIN
        if parsed.scheme not in ('http', 'https'):
            return _DEFAULT_ORIGIN
        host = (parsed.hostname or '').lower()
        if host == 'docklabs.ai' or host.endswith('.docklabs.ai'):
            return origin
        if getattr(settings, 'DEBUG', False) and host in ('localhost', '127.0.0.1'):
            return origin
        return _DEFAULT_ORIGIN
