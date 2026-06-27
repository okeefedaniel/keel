"""/ops/ — cross-product operational console.

Three rows:
1. Scheduling — Keel-local scheduling jobs (v1 scope; cross-product
   roll-up deferred to a sibling `/api/v1/scheduling-feed/` endpoint
   not yet built).
2. Activity system-events lane — cross-product fan-out via
   `keel.feed.client.fetch_product_activity`. The primary payload.
3. Canary — Keel-local canary flags (v1 scope; per-product canary
   fan-out requires distributing `KEEL_METRICS_TOKEN` and is deferred).

Rate limit + permissions mirror /audit/ exactly.
"""
from __future__ import annotations

import time

from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_GET

from .aggregator import aggregate_activity
from .forms import OpsFilterForm
from .permissions import can_view_ops, visible_products_for

RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60


def _rate_limited(user_id: int) -> bool:
    """30 req / 60 s per authenticated user — matches /audit/ exactly."""
    key = f'keel:ops_view_rate:{user_id}'
    now = time.time()
    bucket = cache.get(key) or []
    bucket = [t for t in bucket if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= RATE_LIMIT_REQUESTS:
        return True
    bucket.append(now)
    cache.set(key, bucket, timeout=RATE_LIMIT_WINDOW_SECONDS)
    return False


@method_decorator(require_GET, name='dispatch')
class OpsConsoleView(View):
    template_name = 'ops/console.html'

    def dispatch(self, request, *args, **kwargs):
        if not can_view_ops(request.user):
            return HttpResponseForbidden(
                '/ops/ requires superuser or system_admin / agency_admin '
                'ProductAccess.'
            )
        if _rate_limited(request.user.pk):
            return HttpResponseForbidden(
                'Rate limit exceeded. Try again in a minute.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        allowed_products = visible_products_for(request.user)
        form = OpsFilterForm(request.GET, visible_products=allowed_products)
        form.is_valid()
        window_start, window_end = form.cleaned_window()

        selected = form.cleaned_data.get('products') or []
        if selected:
            scoped = [c for c in selected if c in allowed_products]
        else:
            scoped = list(allowed_products)

        status = form.cleaned_data.get('status') or 'any'
        q = (form.cleaned_data.get('q') or '').strip()

        # Row 2 — the main payload. Cross-product Activity system-events fan-out.
        # Filter to actor=None system events ONLY by passing status non-'any'
        # OR by relying on the per-product activity-feed endpoint to scope to
        # `actor IS NULL` (which the reference example does). For v1 we trust
        # the products to do the right thing; future tighten to enforce here.
        activity_result = aggregate_activity(
            visible_products=scoped,
            window_start=window_start,
            window_end=window_end,
            q=q,
            status=status,
        )

        # Row 1 — Keel-local scheduling roll-up (v1).
        scheduling_rows = _local_scheduling_rows()

        # Row 3 — Keel-local canary (v1).
        canary = _local_canary_payload()

        context = {
            'form': form,
            'activity_result': activity_result,
            'scheduling_rows': scheduling_rows,
            'canary': canary,
            'window_start': window_start,
            'window_end': window_end,
            'visible_products': allowed_products,
            'scoped_products': scoped,
            'page_title': 'Operations Console',
        }
        return render(request, self.template_name, context)


def _local_scheduling_rows():
    """Return Keel's own ScheduledJob rows + their last CommandRun.

    Mirror of `/scheduling/` dashboard but compressed to "name + last-run-status
    + cron". Cross-product roll-up requires a per-product endpoint that doesn't
    exist yet — when it does, this function turns into a fan-out like
    aggregate_activity above.
    """
    try:
        from keel.scheduling.models import CommandRun, ScheduledJob
    except Exception:
        return []

    rows = []
    for job in ScheduledJob.objects.order_by('owner_product', 'name'):
        last_run = (
            CommandRun.objects.filter(job=job)
            .order_by('-started_at')
            .first()
        )
        rows.append({
            'name': job.name,
            'slug': job.slug,
            'cron': job.cron_expression,
            'owner': job.owner_product,
            'enabled': job.enabled,
            'last_status': last_run.status if last_run else 'never_run',
            'last_started_at': last_run.started_at if last_run else None,
            'last_duration_ms': last_run.duration_ms if last_run else None,
        })
    return rows


def _local_canary_payload():
    """Return Keel's own canary payload. Fail-soft."""
    try:
        from keel.ops.canary import build_canary_payload
        return build_canary_payload()
    except Exception:
        return None
