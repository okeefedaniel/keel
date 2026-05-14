"""Invariants for the KEEL_PRODUCT_NAME / KEEL_PRODUCT_CODE split (v0.37.0).

`KEEL_PRODUCT_NAME` is the TitleCase display label rendered to users.
`KEEL_PRODUCT_CODE` is the lowercase machine key that matches
`ProductAccess.Product` values and must be used for every ACL / DB
lookup. The two settings are independent on purpose so the v0.36.0
feedback-widget casing bug (a `KEEL_PRODUCT_NAME` reader that forgot
to `.lower()` and silently mismatched every ProductAccess row) is
structurally impossible.

These tests pin the contract: `get_product_code()` prefers
`KEEL_PRODUCT_CODE` when set, falls back to lowercased
`KEEL_PRODUCT_NAME` when not, and never returns a TitleCase string.
"""
from __future__ import annotations

from django.test import override_settings

from keel.core.utils import get_product_code


@override_settings(KEEL_PRODUCT_CODE='beacon', KEEL_PRODUCT_NAME='Beacon')
def test_prefers_explicit_code_when_set():
    assert get_product_code() == 'beacon'


@override_settings(KEEL_PRODUCT_CODE='', KEEL_PRODUCT_NAME='Beacon')
def test_falls_back_to_lowercased_name_when_code_unset():
    assert get_product_code() == 'beacon'


@override_settings(KEEL_PRODUCT_CODE='harbor', KEEL_PRODUCT_NAME='Display Only Label')
def test_code_and_name_can_diverge():
    # Name is for humans, code is for machines. They are independent.
    assert get_product_code() == 'harbor'


@override_settings(KEEL_PRODUCT_CODE='', KEEL_PRODUCT_NAME='')
def test_returns_empty_string_when_both_unset():
    assert get_product_code() == ''


def test_keel_site_settings_code_matches_name_lowercased():
    """The Keel admin console itself must follow the convention."""
    from django.conf import settings
    assert settings.KEEL_PRODUCT_CODE == settings.KEEL_PRODUCT_NAME.lower()
    assert settings.KEEL_PRODUCT_CODE == get_product_code()
