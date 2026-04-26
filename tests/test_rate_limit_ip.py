"""rate_limit decorator must use the trusted-proxy-aware IP extractor.

A leftmost X-Forwarded-For hop is forgeable by any client; trusting it
defeats per-IP rate limiting. With KEEL_TRUSTED_PROXY_COUNT=0 the
decorator should fall back to REMOTE_ADDR and ignore the spoofed header.
"""
from __future__ import annotations

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from keel.core.utils import rate_limit


@rate_limit(max_requests=2, window=60)
def _view(request):
    return HttpResponse('ok')


def _hit(remote_addr: str, xff: str | None = None):
    rf = RequestFactory()
    extra = {'REMOTE_ADDR': remote_addr}
    if xff:
        extra['HTTP_X_FORWARDED_FOR'] = xff
    return _view(rf.get('/x/', **extra))


@override_settings(KEEL_TRUSTED_PROXY_COUNT=0)
def test_spoofed_xff_does_not_create_new_buckets():
    cache.clear()
    # Same REMOTE_ADDR; attacker rotates X-Forwarded-For. With trusted
    # proxy count = 0 the header is ignored and all hits go to one bucket.
    assert _hit('10.0.0.5', 'aaa').status_code == 200
    assert _hit('10.0.0.5', 'bbb').status_code == 200
    blocked = _hit('10.0.0.5', 'ccc')
    assert blocked.status_code == 429
