"""Keel site middleware."""


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
            response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response['Access-Control-Max-Age'] = '86400'
            return response

        response = self.get_response(request)

        # Add CORS headers to API responses
        if request.path.startswith('/api/'):
            response['Access-Control-Allow-Origin'] = self._get_origin(request)
            response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

        return response

    def _get_origin(self, request):
        """Return the requesting origin if it's a DockLabs domain."""
        origin = request.META.get('HTTP_ORIGIN', '')
        if origin and 'docklabs.ai' in origin:
            return origin
        # Also allow localhost for development
        if origin and ('localhost' in origin or '127.0.0.1' in origin):
            return origin
        return 'https://keel.docklabs.ai'
