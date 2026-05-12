"""Tests for keel_site.audit.templatetags.audit_tags.

Locks the scheme allowlist (decision A1) and the protocol-relative
URL rejection (decision H3) so the deep-link surface cannot be turned
into a stored-XSS vector.
"""
from django.template import Context, Template
from django.test import RequestFactory

from keel_site.audit.templatetags.audit_tags import _is_safe_url, audit_deep_link


def test_is_safe_url_javascript_blocked():
    assert _is_safe_url('javascript:alert(1)') is False
    assert _is_safe_url('JAVASCRIPT:alert(1)') is False


def test_is_safe_url_data_blocked():
    assert _is_safe_url('data:text/html,<script>x</script>') is False


def test_is_safe_url_protocol_relative_blocked():
    """Decision H3: //evil.com inherits page scheme, routes to arbitrary host."""
    assert _is_safe_url('//evil.com/x') is False


def test_is_safe_url_https_allowed():
    assert _is_safe_url('https://harbor.docklabs.ai/grants/42/') is True


def test_is_safe_url_http_allowed():
    assert _is_safe_url('http://localhost:8000/grants/42/') is True


def test_is_safe_url_absolute_path_allowed():
    assert _is_safe_url('/grants/42/') is True


def test_is_safe_url_empty_string():
    # Empty string fails the // and / prefix checks and urlsplit('')
    # returns an empty scheme — not in the allowlist. False is correct.
    assert _is_safe_url('') is False


def test_audit_deep_link_renders_safe_link():
    out = audit_deep_link({
        'entity_type': 'grant', 'entity_id': '42',
        'deep_link_snapshot': 'https://harbor.docklabs.ai/grants/42/',
    })
    s = str(out)
    assert 'href="https://harbor.docklabs.ai/grants/42/"' in s
    assert 'target="_blank"' in s
    assert 'rel="noopener noreferrer"' in s
    assert 'grant 42' in s


def test_audit_deep_link_escapes_label_when_unsafe():
    """A javascript: URL falls back to plain escaped text."""
    out = audit_deep_link({
        'entity_type': 'grant', 'entity_id': '42',
        'deep_link_snapshot': 'javascript:alert(1)',
    })
    s = str(out)
    assert 'href' not in s
    assert 'grant 42' in s


def test_audit_deep_link_empty_when_no_entity():
    out = audit_deep_link({
        'entity_type': '', 'entity_id': '', 'deep_link_snapshot': '',
    })
    assert str(out) == ''


def test_audit_deep_link_plain_text_when_no_snapshot():
    out = audit_deep_link({
        'entity_type': 'session', 'entity_id': 'abc',
        'deep_link_snapshot': '',
    })
    s = str(out)
    assert 'href' not in s
    assert 'session abc' in s


def test_filter_link_replaces_dimension():
    """Clicking a product chip replaces (not appends) the products param."""
    rf = RequestFactory()
    request = rf.get('/audit/', {'products': 'harbor', 'q': 'dan'})
    tpl = Template(
        '{% load audit_tags %}{% filter_link "products" "beacon" %}'
    )
    rendered = tpl.render(Context({'request': request}))
    assert 'products=beacon' in rendered
    assert 'products=harbor' not in rendered  # replaced
    assert 'q=dan' in rendered  # other params preserved


def test_filter_link_empty_value_renders_empty():
    rf = RequestFactory()
    request = rf.get('/audit/')
    tpl = Template('{% load audit_tags %}{% filter_link "user" "" %}')
    assert tpl.render(Context({'request': request})) == ''
