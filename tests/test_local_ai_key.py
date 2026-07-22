"""Tests for the ``KEEL_LOCAL_AI_KEY`` opt-in (in-product, local-first AI key).

When a suite-mode product sets ``KEEL_LOCAL_AI_KEY = True`` it stores the
Anthropic key in its OWN database and renders the key UI in-product — Keel
stays invisible (no click-out to ``keel.docklabs.ai``). When the flag is off
(the default), suite-mode behavior is unchanged: the panel is a read-only
mirror linking to the IdP, and the AI gate trusts the ``ai_key_present`` OIDC
claim. Standalone products are already editable + local-first regardless.

Covers:
- ``local_ai_key_enabled()`` reads the flag.
- ``_ai_key_is_editable()`` truth table across the three deployment modes.
- The ``ai_key_prompt`` link (``_ai_settings_url``) stays in-product when the
  flag is on, links out to the IdP when off.
- The AI gate (``_user_has_key``) ignores the OIDC claim when the flag is on.
- ``AIPanel`` is editable and writes the product-local field in suite mode
  when the flag is on; stays a read-only mirror when off.
"""

from __future__ import annotations

import pytest
from django.test import RequestFactory, override_settings

pytest.importorskip('cryptography')


# Settings that put keel into "suite-mode product" (an OIDC client of Keel),
# NOT the IdP itself. is_suite_mode() -> True; _identity_is_editable() -> False.
SUITE = dict(KEEL_OIDC_CLIENT_ID='test-client', KEEL_IS_IDP=False, DEMO_MODE=False)


def _gen_key():
    from keel.security.encryption import generate_key
    return generate_key()


@pytest.fixture
def user(db, settings):
    from keel.accounts.models import KeelUser, Organization
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    org = Organization.objects.create(slug='local-ai-key-org', name='Test')
    return KeelUser.objects.create(
        username='local-ai-user', email='localai@example.test', organization=org,
    )


# ---------------------------------------------------------------------------
# local_ai_key_enabled()
# ---------------------------------------------------------------------------
def test_local_ai_key_enabled_defaults_false():
    from keel.core.utils import local_ai_key_enabled
    assert local_ai_key_enabled() is False


@override_settings(KEEL_LOCAL_AI_KEY=True)
def test_local_ai_key_enabled_reads_flag():
    from keel.core.utils import local_ai_key_enabled
    assert local_ai_key_enabled() is True


# ---------------------------------------------------------------------------
# _ai_key_is_editable() truth table
# ---------------------------------------------------------------------------
def test_ai_key_editable_standalone():
    """Standalone (no OIDC client id) — editable regardless of the flag."""
    from keel.settings.builtin_panels import _ai_key_is_editable
    with override_settings(KEEL_OIDC_CLIENT_ID='', KEEL_IS_IDP=False):
        assert _ai_key_is_editable() is True


def test_ai_key_not_editable_suite_flag_off():
    from keel.settings.builtin_panels import _ai_key_is_editable
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=False):
        assert _ai_key_is_editable() is False


def test_ai_key_editable_suite_flag_on():
    from keel.settings.builtin_panels import _ai_key_is_editable
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        assert _ai_key_is_editable() is True


# ---------------------------------------------------------------------------
# _ai_settings_url() — where the "add your key" prompt links
# ---------------------------------------------------------------------------
def test_ai_settings_url_in_product_when_flag_on():
    from keel.core.templatetags.keel_tags import _ai_settings_url
    with override_settings(
        **SUITE, KEEL_LOCAL_AI_KEY=True,
        KEEL_OIDC_ISSUER='https://keel.docklabs.ai',
    ):
        # In-product reverse, never the issuer host.
        assert _ai_settings_url() == '/settings/ai/'


def test_ai_settings_url_links_out_when_flag_off():
    from keel.core.templatetags.keel_tags import _ai_settings_url
    with override_settings(
        **SUITE, KEEL_LOCAL_AI_KEY=False,
        KEEL_OIDC_ISSUER='https://keel.docklabs.ai',
    ):
        assert _ai_settings_url() == 'https://keel.docklabs.ai/settings/ai/'


def test_ai_settings_url_in_product_standalone():
    from keel.core.templatetags.keel_tags import _ai_settings_url
    with override_settings(KEEL_OIDC_CLIENT_ID='', KEEL_IS_IDP=False):
        assert _ai_settings_url() == '/settings/ai/'


# ---------------------------------------------------------------------------
# _user_has_key() — the AI gate's key-presence check
# ---------------------------------------------------------------------------
def _link_keel_account_with_key_claim(user):
    """Attach a keel SocialAccount reporting ai_key_present=True (no local key)."""
    from allauth.socialaccount.models import SocialAccount
    SocialAccount.objects.create(
        user=user, provider='keel', uid=str(user.pk),
        extra_data={'userinfo': {'ai_key_present': True}},
    )


def test_user_has_key_trusts_claim_when_flag_off(db, user):
    """Suite default: empty local field but a key on the Keel identity → True."""
    from keel.core.ai_access import _user_has_key
    _link_keel_account_with_key_claim(user)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=False):
        assert _user_has_key(user) is True


def test_user_has_key_ignores_claim_when_flag_on(db, user):
    """Local-AI-key mode: the claim is irrelevant — only the local field counts."""
    from keel.core.ai_access import _user_has_key
    _link_keel_account_with_key_claim(user)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        assert _user_has_key(user) is False


def test_user_has_key_local_field_wins_when_flag_on(db, user, settings):
    """A locally-stored key reads as present even in local-AI-key mode."""
    from keel.core.ai_access import _user_has_key
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    user.anthropic_api_key = 'sk-ant-local-key-1234567890abcdefghij'
    user.save(update_fields=['anthropic_api_key_encrypted'])
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        assert _user_has_key(user) is True


# ---------------------------------------------------------------------------
# AIPanel — editable + local-first in suite mode when the flag is on
# ---------------------------------------------------------------------------
def _post_request(user, data):
    from django.contrib.messages.storage.fallback import FallbackStorage
    req = RequestFactory().post('/settings/ai/', data)
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def _get_request(user):
    req = RequestFactory().get('/settings/ai/')
    req.user = user
    return req


def test_aipanel_editable_context_suite_flag_on(db, user):
    from keel.settings.builtin_panels import AIPanel
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        ctx = AIPanel().get_context(_get_request(user))
    assert ctx['editable'] is True
    # Empty local field, so no false "configured" from the OIDC claim.
    assert ctx['has_key'] is False


def test_aipanel_not_editable_context_suite_flag_off(db, user):
    from keel.settings.builtin_panels import AIPanel
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=False):
        ctx = AIPanel().get_context(_get_request(user))
    assert ctx['editable'] is False


def test_aipanel_post_writes_local_field_suite_flag_on(db, user, settings):
    from keel.settings.builtin_panels import AIPanel
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    key = 'sk-ant-in-product-key-1234567890abcdefghij'
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        result = AIPanel().post(_post_request(user, {'_action': 'set',
                                                     'anthropic_api_key': key}))
    assert result is None  # success → PRG redirect
    user.refresh_from_db()
    assert user.has_anthropic_key() is True
    assert user.anthropic_api_key == key


def test_aipanel_post_blocked_suite_flag_off(db, user, settings):
    from keel.settings.builtin_panels import AIPanel
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=False):
        result = AIPanel().post(_post_request(user, {'_action': 'set',
                                                     'anthropic_api_key': 'sk-ant-xxxxxxxxxxxxxxxxxxxx'}))
    # Non-editable: returns re-render context (not None), and never writes.
    assert result is not None
    user.refresh_from_db()
    assert user.has_anthropic_key() is False


# ---------------------------------------------------------------------------
# Unconfigured encryption — the panel must degrade, not 500
# ---------------------------------------------------------------------------
# EncryptedTextField.get_db_prep_save raises ImproperlyConfigured when
# neither KEEL_ENCRYPTION_KEYS nor KEEL_ENCRYPTION_KEY is set. Beacon prod
# 500'd on the first in-product key save (2026-07-22) because the env var
# had never been needed before the page shipped. The panel now probes the
# key config up front and renders an admin-facing fix-it message instead.

def _unset_encryption(settings, monkeypatch):
    settings.KEEL_ENCRYPTION_KEYS = ''
    settings.KEEL_ENCRYPTION_KEY = ''
    monkeypatch.delenv('KEEL_ENCRYPTION_KEYS', raising=False)
    monkeypatch.delenv('KEEL_ENCRYPTION_KEY', raising=False)


# Full-page tests render the shared chrome; use plain staticfiles storage so
# the manifest (built by collectstatic, absent in test runs) isn't required.
_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def test_encryption_configured_helper_truth_table(settings, monkeypatch):
    from keel.settings.builtin_panels import _encryption_configured
    _unset_encryption(settings, monkeypatch)
    assert _encryption_configured() is False
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    assert _encryption_configured() is True


def test_aipanel_get_context_encryption_unconfigured(db, user, settings, monkeypatch):
    """GET with no encryption key: no exception, context flags the gap."""
    from keel.settings.builtin_panels import AIPanel
    _unset_encryption(settings, monkeypatch)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        ctx = AIPanel().get_context(_get_request(user))
    assert ctx['editable'] is True
    assert ctx['encryption_configured'] is False
    assert 'KEEL_ENCRYPTION_KEYS' in ctx['encryption_unconfigured_message']


def test_aipanel_get_context_encryption_configured(db, user, settings):
    from keel.settings.builtin_panels import AIPanel
    settings.KEEL_ENCRYPTION_KEYS = _gen_key()
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        ctx = AIPanel().get_context(_get_request(user))
    assert ctx['encryption_configured'] is True


def test_aipanel_post_encryption_unconfigured_no_500(db, user, settings, monkeypatch):
    """POST with no encryption key: re-renders (no ImproperlyConfigured), writes nothing."""
    from keel.settings.builtin_panels import AIPanel
    _unset_encryption(settings, monkeypatch)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        result = AIPanel().post(_post_request(user, {
            '_action': 'set',
            'anthropic_api_key': 'sk-ant-would-500-1234567890abcdefghij',
        }))
    assert result is not None  # re-render, not the success/PRG path
    assert result['encryption_configured'] is False
    user.refresh_from_db()
    assert user.has_anthropic_key() is False


def test_ai_panel_template_hides_form_when_unconfigured(db, user, settings, monkeypatch):
    """Rendered panel shows the admin message and no key-entry form."""
    from django.template.loader import render_to_string
    from keel.settings.builtin_panels import AIPanel
    _unset_encryption(settings, monkeypatch)
    with override_settings(**SUITE, KEEL_LOCAL_AI_KEY=True):
        ctx = AIPanel().get_context(_get_request(user))
        html = render_to_string('keel/settings/panels/ai.html', ctx)
    assert 'KEEL_ENCRYPTION_KEYS' in html
    assert 'generate_key()' in html
    assert 'name="anthropic_api_key"' not in html  # form hidden


def test_settings_ai_page_get_200_when_unconfigured(db, user, settings, monkeypatch, client):
    """Full-stack GET /settings/ai/ → 200 with the message, no 500."""
    from keel.settings import builtin_panels
    _unset_encryption(settings, monkeypatch)
    # Make the panel visible without wiring org subscriptions + ProductAccess.
    monkeypatch.setattr(
        builtin_panels.AIPanel, 'is_visible', lambda self, u: True,
    )
    client.force_login(user)
    with override_settings(KEEL_OIDC_CLIENT_ID='', KEEL_IS_IDP=False, STORAGES=_STORAGES):
        resp = client.get('/settings/ai/')
    assert resp.status_code == 200
    assert 'KEEL_ENCRYPTION_KEYS' in resp.content.decode()


def test_settings_ai_page_post_no_500_when_unconfigured(db, user, settings, monkeypatch, client):
    """Full-stack POST: re-renders the panel with the message, never raises."""
    from keel.settings import builtin_panels
    _unset_encryption(settings, monkeypatch)
    monkeypatch.setattr(
        builtin_panels.AIPanel, 'is_visible', lambda self, u: True,
    )
    client.force_login(user)
    with override_settings(KEEL_OIDC_CLIENT_ID='', KEEL_IS_IDP=False, STORAGES=_STORAGES):
        resp = client.post('/settings/ai/', {
            'panel': 'ai', '_action': 'set',
            'anthropic_api_key': 'sk-ant-would-500-1234567890abcdefghij',
        })
    # Error re-render path (panel.post returned context), not a 500.
    assert resp.status_code in (200, 400)
    assert 'KEEL_ENCRYPTION_KEYS' in resp.content.decode()
    user.refresh_from_db()
    assert user.has_anthropic_key() is False
