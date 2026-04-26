"""APICorsMiddleware must use parsed-host comparison, not substring match."""
from __future__ import annotations

from django.http import HttpResponse
from django.test import RequestFactory

from keel_site.middleware import APICorsMiddleware


def _mw():
    return APICorsMiddleware(lambda req: HttpResponse('ok'))


def _origin_for(http_origin: str) -> str:
    rf = RequestFactory()
    request = rf.get('/api/foo/', HTTP_ORIGIN=http_origin)
    return _mw()._get_origin(request)


def test_legitimate_subdomain_allowed():
    assert _origin_for('https://harbor.docklabs.ai') == 'https://harbor.docklabs.ai'


def test_apex_allowed():
    assert _origin_for('https://docklabs.ai') == 'https://docklabs.ai'


def test_substring_attack_rejected():
    # Pre-fix this would echo back; now must fall to the default origin.
    assert _origin_for('https://attackerdocklabs.ai') == 'https://keel.docklabs.ai'


def test_suffix_attack_rejected():
    assert _origin_for('https://docklabs.ai.evil.example') == 'https://keel.docklabs.ai'


def test_non_http_scheme_rejected():
    assert _origin_for('javascript://docklabs.ai') == 'https://keel.docklabs.ai'
