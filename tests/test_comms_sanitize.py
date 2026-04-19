"""Tests for ``keel.comms.sanitize``.

The sanitizer is the last line of defense before inbound agency email
HTML is rendered in the comms panel. These tests pin the tag/attribute
allowlist against common XSS payloads.
"""
import pytest

from keel.comms.sanitize import sanitize_html, strip_all_html


def test_script_tag_stripped():
    dirty = '<p>hello</p><script>alert(1)</script>'
    assert '<script' not in sanitize_html(dirty)
    assert 'alert(1)' not in sanitize_html(dirty)


def test_event_handler_stripped():
    dirty = '<a href="https://example.com" onclick="bad()">x</a>'
    cleaned = sanitize_html(dirty)
    assert 'onclick' not in cleaned
    assert 'bad()' not in cleaned


def test_javascript_href_stripped():
    dirty = '<a href="javascript:alert(1)">x</a>'
    cleaned = sanitize_html(dirty)
    assert 'javascript:' not in cleaned


def test_data_url_href_stripped():
    dirty = '<a href="data:text/html,<script>alert(1)</script>">x</a>'
    cleaned = sanitize_html(dirty)
    assert 'data:text/html' not in cleaned


def test_style_tag_and_attribute_stripped():
    dirty = '<p style="background:url(javascript:alert(1))">x</p><style>body{}</style>'
    cleaned = sanitize_html(dirty)
    assert 'javascript:' not in cleaned
    assert '<style' not in cleaned


def test_allowed_tags_preserved():
    clean = '<p><strong>Hi</strong> <em>there</em></p>'
    assert sanitize_html(clean) == clean


def test_external_link_gets_rel_noopener():
    cleaned = sanitize_html('<a href="https://example.com">x</a>')
    assert 'noopener' in cleaned


def test_empty_input_returns_empty_string():
    assert sanitize_html('') == ''
    assert sanitize_html(None) == ''


def test_strip_all_html_removes_tags():
    assert strip_all_html('<p>Hello <b>world</b></p>') == 'Hello world'
    assert strip_all_html('<script>alert(1)</script>x') == 'x'
