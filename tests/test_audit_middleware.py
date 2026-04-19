"""Tests for ``keel.core.middleware.AuditMiddleware`` try/finally clear.

Before the try/finally fix, an exception raised in a downstream view
would leave the threadlocal audit context (user, ip) set, so the NEXT
request on the same worker thread would write audit rows attributed to
the previous request's user.
"""
import pytest


def _make_request():
    from django.test import RequestFactory
    return RequestFactory().get('/anything/')


def test_context_cleared_on_view_exception():
    from keel.core.middleware import AuditMiddleware
    from keel.core.audit_signals import get_audit_context

    def _boom(request):
        raise RuntimeError('simulated view failure')

    mw = AuditMiddleware(_boom)
    request = _make_request()

    with pytest.raises(RuntimeError):
        mw(request)

    ctx = get_audit_context()
    # Context must be cleared even though get_response raised.
    assert ctx.get('user') is None
    assert ctx.get('ip_address') is None


def test_context_cleared_on_normal_response():
    from django.http import HttpResponse

    from keel.core.middleware import AuditMiddleware
    from keel.core.audit_signals import get_audit_context

    mw = AuditMiddleware(lambda r: HttpResponse('ok'))
    request = _make_request()
    response = mw(request)

    assert response.status_code == 200
    ctx = get_audit_context()
    assert ctx.get('user') is None
    assert ctx.get('ip_address') is None
