"""/audit/ — cross-product audit log browse."""
from __future__ import annotations

import time
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_GET

from keel.accounts.models import AuditLog

from .aggregator import aggregate_audit
from .forms import AuditFilterForm
from .permissions import can_view_audit, visible_products_for

PAGE_SIZE = 50
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60


def _rate_limited(user_id: int) -> bool:
    """30 req / 60 s per authenticated user (review decision A4)."""
    key = f'keel:audit_view_rate:{user_id}'
    now = time.time()
    bucket = cache.get(key) or []
    bucket = [t for t in bucket if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= RATE_LIMIT_REQUESTS:
        return True
    bucket.append(now)
    cache.set(key, bucket, timeout=RATE_LIMIT_WINDOW_SECONDS)
    return False


@method_decorator(require_GET, name='dispatch')
class AuditLogListView(View):
    template_name = 'audit/list.html'

    def dispatch(self, request, *args, **kwargs):
        if not can_view_audit(request.user):
            return HttpResponseForbidden(
                'Audit log requires superuser or agency admin.'
            )
        if _rate_limited(request.user.pk):
            return HttpResponseForbidden(
                'Rate limit exceeded. Try again in a minute.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        allowed_products = visible_products_for(request.user)
        # Always pass GET data (even empty) so the form binds and
        # cleaned_data populates. Passing ``request.GET or None`` was a
        # 500-on-first-visit footgun: unbound forms have no cleaned_data,
        # and cleaned_window() reads it.
        form = AuditFilterForm(request.GET, visible_products=allowed_products)
        form.is_valid()
        window_start, window_end = form.cleaned_window()

        # Scope products to what the user is allowed to see AND what they
        # picked in the form. An empty pick = show everything they may see.
        selected = form.cleaned_data.get('products') or []
        if selected:
            scoped = [c for c in selected if c in allowed_products]
        else:
            scoped = list(allowed_products)

        actions = form.cleaned_data.get('actions') or []
        q = (form.cleaned_data.get('q') or '').strip()

        result = aggregate_audit(
            visible_products=scoped,
            window_start=window_start,
            window_end=window_end,
            q=q,
            actions=actions,
        )

        paginator = Paginator(result.rows, PAGE_SIZE)
        page_number = request.GET.get('page') or 1
        page = paginator.get_page(page_number)

        # Preserve filter params on pagination links.
        qs = request.GET.copy()
        qs.pop('page', None)
        base_qs = qs.urlencode()

        sec_event_url = ''
        if result.security_event_count:
            qs_sec = request.GET.copy()
            qs_sec.pop('page', None)
            qs_sec.setlist('actions', ['security_event'])
            sec_event_url = '?' + qs_sec.urlencode()

        all_failed = bool(result.per_product) and all(
            s.status != 'ok' for s in result.per_product.values()
        )

        return render(request, self.template_name, {
            'form': form,
            'page': page,
            'paginator': paginator,
            'per_product': result.per_product,
            'window_start': window_start,
            'window_end': window_end,
            'fleet_products': settings.KEEL_FLEET_PRODUCTS,
            'allowed_products': allowed_products,
            'action_choices': AuditLog.Action.choices,
            'base_querystring': base_qs,
            'security_event_count': result.security_event_count,
            'security_event_url': sec_event_url,
            'all_failed': all_failed,
        })
