"""Direct coverage for the shared redirect guard in keel.core.utils.

``safe_redirect_url`` gained an ``extra_hosts`` argument (and its companion
``fleet_product_hosts``) so the notification click-through route could reuse
it instead of carrying a second copy of the same open-redirect check.
"""
from __future__ import annotations

import pytest
from django.test import RequestFactory, override_settings

from keel.core.utils import fleet_product_hosts, safe_redirect_url

FLEET = [
    {'name': 'Harbor', 'code': 'harbor', 'url': 'https://harbor.docklabs.ai/dashboard/'},
    {'name': 'Helm', 'code': 'helm', 'url': 'https://helm.docklabs.ai/dashboard/'},
]


def _req(secure=False):
    return RequestFactory().get('/', secure=secure)


def test_relative_path_is_allowed():
    assert safe_redirect_url(_req(), '/invitations/abc/') == '/invitations/abc/'


@pytest.mark.parametrize('url', [
    'https://evil.example.com/steal',
    '//evil.example.com/steal',
    'javascript:alert(1)',
    'https://user@evil.example.com/',
])
def test_offsite_targets_fall_back(url):
    assert safe_redirect_url(_req(), url, fallback='/dashboard/') == '/dashboard/'


def test_empty_url_returns_the_fallback():
    assert safe_redirect_url(_req(), '', fallback='') == ''


@override_settings(KEEL_FLEET_PRODUCTS=FLEET)
def test_extra_hosts_admits_a_fleet_peer():
    target = 'https://harbor.docklabs.ai/applications/7/'
    assert safe_redirect_url(
        _req(secure=True), target, fallback='', extra_hosts=fleet_product_hosts(),
    ) == target


@override_settings(KEEL_FLEET_PRODUCTS=FLEET)
def test_a_peer_not_in_the_fleet_is_still_refused():
    assert safe_redirect_url(
        _req(secure=True), 'https://notapeer.docklabs.ai/x',
        fallback='', extra_hosts=fleet_product_hosts(),
    ) == ''


@override_settings(KEEL_FLEET_PRODUCTS=FLEET)
def test_secure_request_refuses_an_http_downgrade_to_a_peer():
    assert safe_redirect_url(
        _req(secure=True), 'http://harbor.docklabs.ai/x',
        fallback='', extra_hosts=fleet_product_hosts(),
    ) == ''


@override_settings(KEEL_FLEET_PRODUCTS=FLEET)
def test_fleet_product_hosts_reads_every_declared_peer():
    assert fleet_product_hosts() == {'harbor.docklabs.ai', 'helm.docklabs.ai'}


@override_settings(KEEL_FLEET_PRODUCTS=[
    None, 'not-a-dict', {}, {'url': None}, {'name': 'No URL'},
    {'name': 'Harbor', 'url': 'https://harbor.docklabs.ai/dashboard/'},
])
def test_fleet_product_hosts_skips_malformed_entries():
    """A junk row in one product's fleet list must never raise."""
    assert fleet_product_hosts() == {'harbor.docklabs.ai'}


@override_settings(KEEL_FLEET_PRODUCTS=None)
def test_fleet_product_hosts_tolerates_an_unset_fleet():
    assert fleet_product_hosts() == set()
