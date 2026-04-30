"""Canary endpoint view.

Mounted by products at their preferred URL (helm uses ``/api/v1/metrics/``).
Auth: staff session OR ``Authorization: Bearer $KEEL_METRICS_TOKEN``.
"""
import hmac

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse

from keel.ops.canary import build_canary_payload


def _has_metrics_token(request) -> bool:
    """Return True iff request carries a valid bearer token."""
    expected = getattr(settings, 'KEEL_METRICS_TOKEN', '') or ''
    if not expected:
        return False
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Bearer '):
        return False
    return hmac.compare_digest(auth[7:].strip(), expected)


def canary_view(extras_callable=None):
    """Return a Django view that renders the canary JSON payload.

    Use as::

        # product/api/metrics.py
        from keel.ops.views import canary_view
        metrics = canary_view(extras_callable=_my_extras)

    Or for a no-extras endpoint, the bundled URL include is enough::

        # product/urls.py
        path('api/v1/metrics/', include('keel.ops.urls')),
    """
    def _view(request):
        if _has_metrics_token(request):
            return JsonResponse(build_canary_payload(extras_callable))
        return _staff_only(request, extras_callable)
    return _view


@staff_member_required
def _staff_only(request, extras_callable):
    return JsonResponse(build_canary_payload(extras_callable))


# Default no-extras endpoint, used by ``include('keel.ops.urls')``.
metrics = canary_view()
