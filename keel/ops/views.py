"""Canary endpoint view.

Mounted by products at their preferred URL (helm uses ``/api/v1/metrics/``).
Auth: superuser/system_admin session OR ``Authorization: Bearer
$KEEL_METRICS_TOKEN``. ``is_staff`` alone is NOT sufficient — demo users
are seeded with ``is_staff=True`` so the Django admin works for every
role flavor, and the historical ``is_staff`` gate leaked ops infra to
every demo agency_admin / analyst / reviewer.
"""
import hmac

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse

from keel.ops.canary import build_canary_payload, user_can_view_canary


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

    Auth: bearer token (``KEEL_METRICS_TOKEN``) for external pollers, OR
    a logged-in user who passes :func:`keel.ops.canary.user_can_view_canary`
    (superuser or product ``system_admin``).

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
        if user_can_view_canary(request.user):
            return JsonResponse(build_canary_payload(extras_callable))
        return HttpResponseForbidden('canary access denied')
    return _view


# Default no-extras endpoint, used by ``include('keel.ops.urls')``.
metrics = canary_view()
