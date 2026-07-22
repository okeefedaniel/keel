"""Built-in settings panels shipped with keel itself.

Profile + Account panels handle identity surfaces (basic profile fields,
username change with live availability, email change with verification,
password change). The Notifications panel reuses
``keel.notifications.views.preferences`` rendering.

Identity edits are gated by deployment mode:

- **Standalone** (``KEEL_OIDC_CLIENT_ID`` unset): all panels are editable;
  the local KeelUser row is the source of truth.
- **Suite** (product, OIDC client of Keel): Profile panel is editable
  locally; changes are synced back to Keel IdP best-effort via the
  user's own OIDC access token. Account panel is visible but informational
  — users are linked to ``KEEL_OIDC_ISSUER/settings/account/`` to change
  username, email, or password.
- **Keel IdP** (``KEEL_IS_IDP=True``): all panels editable. Username,
  email, and password edits propagate to every product on the user's
  next login via JWT claims + ``SessionFreshnessMiddleware``.

The standalone `/notifications/preferences/` URL stays live for
backwards compat; it renders the same form as the Notifications panel.
"""
import logging
import os

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm

from keel.core.utils import is_keel_idp, is_suite_mode, local_ai_key_enabled

from .base import SettingsPanel

logger = logging.getLogger(__name__)


def _identity_is_editable() -> bool:
    """Identity edits are allowed on standalone products and on Keel itself.

    Gates AccountPanel (username / email / password). Profile fields are
    gated separately by _profile_is_editable() so they can be edited
    everywhere without changing the credential-change rules; the AI key is
    gated by _ai_key_is_editable() so a product can opt into local AI-key
    storage without unlocking credential edits.
    """
    return is_keel_idp() or not is_suite_mode()


def _ai_key_is_editable() -> bool:
    """The Anthropic-key panel is editable wherever the key is stored locally.

    That's standalone products and Keel itself (``_identity_is_editable``),
    PLUS suite-mode products that opted into local AI-key storage via
    ``KEEL_LOCAL_AI_KEY`` — those store the key in their own DB and render
    the editable form in-product (Keel invisible) instead of the
    "manage on DockLabs" click-out.
    """
    return _identity_is_editable() or local_ai_key_enabled()


def _profile_is_editable() -> bool:
    """Profile fields (name, title, phone, timezone, locale) are editable
    in every deployment mode. In suite mode, saves propagate to Keel IdP
    best-effort via the user's own OIDC access token.
    """
    return True


def _keel_profile_url() -> str:
    """Build the URL the Profile-panel mirror links to in suite mode."""
    issuer = getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or ''
    issuer = issuer.rstrip('/')
    return f'{issuer}/settings/profile/' if issuer else ''


def _keel_account_url() -> str:
    """Build the Keel account-settings URL surfaced in suite-mode Account panel."""
    issuer = getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or ''
    issuer = issuer.rstrip('/')
    return f'{issuer}/settings/account/' if issuer else ''


# ---------------------------------------------------------------------------
# Profile panel — basic profile fields
# ---------------------------------------------------------------------------
class ProfilePanel(SettingsPanel):
    """Edit name, title, phone, timezone, locale.

    Avatar upload lands in Phase 2 of the profile rollout. Username and
    email live on the AccountPanel because their write paths have very
    different side effects (verification email, session invalidation).
    """

    slug = 'profile'
    label = 'Profile'
    icon = 'bi-person-circle'
    order = 10  # floats above Notifications (50)
    description = 'Your name, contact info, and display preferences'

    def get_context(self, request, *, form=None, avatar_error=None):
        from keel.accounts.forms import ProfileForm

        ctx = {
            'editable': True,
            'user': request.user,
            'avatar_error': avatar_error,
            # Surface the bytes ceiling to the template so client-side
            # validation matches the server-side ValueError code.
            'avatar_max_mb': 5,
            'form': form or ProfileForm(instance=request.user),
        }
        # In suite mode, surface a link to Keel for identity settings
        # (username / email / password) that can't be changed in-product.
        account_url = _keel_account_url()
        if account_url and is_suite_mode():
            ctx['keel_account_url'] = account_url
        return ctx

    def post(self, request):
        action = (request.POST.get('_action') or 'profile').strip()
        if action == 'avatar_upload':
            return self._post_avatar_upload(request)
        if action == 'avatar_clear':
            return self._post_avatar_clear(request)
        # Default: profile field edits.
        return self._post_profile(request)

    # --- Sub-handlers --------------------------------------------------
    def _post_profile(self, request):
        from keel.accounts.forms import ProfileForm

        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            # Best-effort sync to Keel IdP in suite mode. Never blocks the
            # local save — failures are logged and silently skipped.
            if is_suite_mode():
                try:
                    from keel.settings.keel_client import sync_profile_to_keel
                    sync_profile_to_keel(request.user, form.cleaned_data)
                except Exception:
                    logger.exception('settings.profile.sync: unexpected error during sync')
            return None
        return self.get_context(request, form=form)

    def _post_avatar_upload(self, request):
        from keel.accounts.services import set_avatar

        upload = request.FILES.get('avatar')
        if upload is None:
            return self.get_context(
                request, avatar_error='Choose a file to upload first.',
            )
        try:
            set_avatar(request.user, upload, actor=request.user)
        except ValueError as exc:
            # Map the structured error codes from set_avatar into a
            # user-friendly inline message. ``str(exc)`` is one of:
            #   "avatar_invalid: too_large"
            #   "avatar_invalid: bad_content_type"
            #   "avatar_invalid: cannot decode image (...)"
            #   "avatar_invalid: unsupported format ..."
            code = str(exc).removeprefix('avatar_invalid: ')
            messages_by_code = {
                'too_large': 'That image is over 5 MB. Choose a smaller file.',
                'bad_content_type': 'Use a JPEG, PNG, or WebP image.',
            }
            friendly = messages_by_code.get(
                code,
                # Fall through for "cannot decode" / "unsupported format"
                # — keep the technical phrase, it's clear enough.
                f"Couldn't process that image: {code}",
            )
            return self.get_context(request, avatar_error=friendly)

        messages.success(request, 'Profile photo updated.')
        return None

    def _post_avatar_clear(self, request):
        from keel.accounts.services import clear_avatar

        if clear_avatar(request.user, actor=request.user):
            messages.success(request, 'Profile photo removed.')
        return None


# ---------------------------------------------------------------------------
# Account panel — username, email, password
# ---------------------------------------------------------------------------
class AccountPanel(SettingsPanel):
    """Manage the credentials that identify and authenticate the user.

    Hidden entirely in suite-mode product deployments — the user edits
    these on Keel itself, not in-product. The panel renders three
    sub-forms (username / email / password) sharing one POST endpoint;
    a hidden ``_action`` field selects which form was submitted.
    """

    slug = 'account'
    label = 'Account'
    icon = 'bi-shield-lock'
    order = 20
    description = 'Username, email, and password'

    def is_visible(self, user) -> bool:
        if not super().is_visible(user):
            return False
        # Always visible: in suite mode we show an informational card
        # linking to Keel for credential edits (gives users a discoverable
        # path), and in standalone mode we show the actual forms.
        return True

    def get_context(self, request, *, username_form=None, email_form=None,
                    password_form=None):
        from keel.accounts.forms import EmailChangeForm, UsernameChangeForm

        ctx = {
            'user': request.user,
            'username_check_url': '/keel/accounts/username-available/',
        }
        if _identity_is_editable():
            ctx.update({
                'username_form': username_form or UsernameChangeForm(user=request.user),
                'email_form': email_form or EmailChangeForm(user=request.user),
                'password_form': password_form or PasswordChangeForm(user=request.user),
            })
        else:
            # Suite mode: render informational card with link to Keel.
            ctx['suite_mode'] = True
            account_url = _keel_account_url()
            if account_url:
                ctx['keel_account_url'] = account_url
        return ctx

    def post(self, request):
        if not _identity_is_editable():
            # Suite mode: no forms to submit, nothing to do.
            return self.get_context(request)

        action = (request.POST.get('_action') or '').strip()

        if action == 'username':
            return self._post_username(request)
        if action == 'email':
            return self._post_email(request)
        if action == 'password':
            return self._post_password(request)

        # Tampered POST — re-render with a generic error.
        messages.error(request, 'Unknown action.')
        return self.get_context(request)

    # --- Sub-handlers --------------------------------------------------
    def _post_username(self, request):
        from keel.accounts.forms import UsernameChangeForm
        from keel.accounts.services import rename_user

        form = UsernameChangeForm(request.POST, user=request.user)
        if not form.is_valid():
            return self.get_context(request, username_form=form)

        try:
            new_username = rename_user(
                request.user,
                form.cleaned_data['username'],
                actor=request.user,
            )
        except ValueError as exc:
            # Race-window collision (someone else took the name between
            # the form-clean uniqueness check and the atomic rename) —
            # surface as a form error and re-render.
            form.add_error('username', str(exc).replace('username_validation: ', ''))
            return self.get_context(request, username_form=form)

        # Refresh the session hash so the user isn't logged out by the
        # AbstractBaseUser.get_session_auth_hash change. The standard
        # Django helper handles this for password changes; usernames
        # don't normally affect the hash, but this is cheap insurance
        # if a project's get_session_auth_hash override depends on it.
        try:
            update_session_auth_hash(request, request.user)
        except Exception:
            logger.debug('AccountPanel: update_session_auth_hash skipped after rename')

        messages.success(request, f'Username changed to {new_username}.')
        return None

    def _post_email(self, request):
        from keel.accounts.forms import EmailChangeForm
        from keel.accounts.services import request_email_change

        form = EmailChangeForm(request.POST, user=request.user)
        if not form.is_valid():
            return self.get_context(request, email_form=form)

        new_email = form.cleaned_data['email']
        try:
            request_email_change(request.user, new_email, request=request)
        except ValueError as exc:
            # Map ``email_invalid: <code>`` to an inline form error.
            code = str(exc).removeprefix('email_invalid: ')
            form.add_error('email', code.replace('_', ' '))
            return self.get_context(request, email_form=form)
        except Exception:
            logger.exception('email change request failed user=%s', request.user.pk)
            messages.error(
                request,
                "Couldn't send the confirmation email. Try again in a moment.",
            )
            return self.get_context(request, email_form=form)

        messages.success(
            request,
            f'Confirmation email sent to {new_email}. Click the link to finish.',
        )
        return None

    def _post_password(self, request):
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if not form.is_valid():
            return self.get_context(request, password_form=form)
        user = form.save()
        # Keep the user logged in after the password rotation. Without
        # this, Django's session-auth-hash invalidation logs them out.
        update_session_auth_hash(request, user)
        messages.success(request, 'Password updated.')
        return None


# ---------------------------------------------------------------------------
# AI panel — Anthropic API key for AI features
# ---------------------------------------------------------------------------
class AIPanel(SettingsPanel):
    """Manage the Anthropic API key that powers AI features.

    Visible only when the user has at least one product with AI enabled
    at the org+user level (layers 1+2 of the three-layer gate). When
    the user has no AI-eligible products, the panel is hidden — adding
    a key would be pointless.

    On Keel itself and on standalone products the panel is editable. On
    suite-mode products it renders an informational mirror linking to Keel
    (``KEEL_OIDC_ISSUER/settings/ai/``) — UNLESS the product opts into
    local AI-key storage with ``KEEL_LOCAL_AI_KEY=True``, in which case the
    panel is editable in-product and the key lives in the product's own DB.
    """

    slug = 'ai'
    label = 'AI'
    icon = 'bi-stars'
    order = 30  # Between Account (20) and Notifications (50).
    description = 'Your Anthropic API key for AI features'

    # Where users go to get a key. Linked from the help text.
    ANTHROPIC_CONSOLE_URL = 'https://console.anthropic.com/settings/keys'

    # Admin-facing message rendered (and used as the POST error) when the
    # deployment has no encryption key configured. Saving would otherwise
    # 500 at EncryptedTextField.get_db_prep_save — happened on Beacon prod
    # 2026-07-22, the first save after the in-product page shipped.
    ENCRYPTION_UNCONFIGURED_MESSAGE = (
        "This product isn't configured for encrypted key storage yet — "
        'set KEEL_ENCRYPTION_KEYS on the service. Generate one with '
        'keel.security.encryption.generate_key().'
    )

    def is_visible(self, user) -> bool:
        if not super().is_visible(user):
            return False
        # Hide entirely when the user has no AI-eligible products.
        # Showing a key field that would never be read is confusing.
        try:
            from keel.core.ai_access import ai_enabled_products_for_user
            return bool(ai_enabled_products_for_user(user))
        except Exception:
            # Defensive: if the ai_access module fails to import (e.g.
            # in a test environment without keel.accounts migrations),
            # show the panel so the user can still set a key. Failing
            # closed here would hide a real settings surface.
            return True

    def get_context(self, request, *, error: str | None = None):
        from keel.core.ai_access import _user_has_key, ai_enabled_products_for_user

        editable = _ai_key_is_editable()
        # Only relevant when the panel manages the product-LOCAL encrypted
        # field; the suite-mode mirror never touches local storage, so
        # report "configured" there to keep the template branch simple.
        encryption_configured = _encryption_configured() if editable else True
        user = request.user
        # When the panel is editable it manages the product-LOCAL encrypted
        # field, so reflect exactly that field — not the ai_key_present OIDC
        # claim, which mirrors the Keel identity's key and can read True while
        # the local field is empty (e.g. before Phase B login-hydration). A
        # False-positive "configured" here would hide the entry form the user
        # actually needs. On non-editable suite panels keep the claim fallback
        # via _user_has_key so the mirror card still shows "set".
        if editable and hasattr(user, 'has_anthropic_key'):
            has_key = user.has_anthropic_key()
        else:
            has_key = _user_has_key(user)
        # key_hint requires the local plaintext — only available when the key
        # is stored locally (Keel itself or standalone mode). In suite mode
        # has_anthropic_key() returns False so the hint is empty anyway.
        key_hint = (
            user.anthropic_key_hint()
            if hasattr(user, 'anthropic_key_hint') and hasattr(user, 'has_anthropic_key') and user.has_anthropic_key()
            else ''
        )
        return {
            'editable': editable,
            'encryption_configured': encryption_configured,
            'encryption_unconfigured_message': self.ENCRYPTION_UNCONFIGURED_MESSAGE,
            'keel_settings_url': _keel_ai_url(),
            'user': user,
            'has_key': has_key,
            'key_hint': key_hint,
            'ai_enabled_products': ai_enabled_products_for_user(user),
            'anthropic_console_url': self.ANTHROPIC_CONSOLE_URL,
            'error': error,
        }

    def post(self, request):
        if not _ai_key_is_editable():
            messages.error(
                request,
                'AI key edits live on DockLabs. Use the link to update.',
            )
            return self.get_context(request)

        if not _encryption_configured():
            # Saving would 500 at EncryptedTextField.get_db_prep_save
            # (ImproperlyConfigured — no KEEL_ENCRYPTION_KEYS). The form
            # is hidden in this state, but guard the POST path too so a
            # stale tab or direct POST re-renders the admin-facing
            # message instead of crashing.
            return self.get_context(request)

        action = (request.POST.get('_action') or 'set').strip()
        user = request.user

        if action == 'remove':
            if hasattr(user, 'anthropic_api_key'):
                user.anthropic_api_key = ''
                user.save(update_fields=['anthropic_api_key_encrypted'])
                messages.success(request, 'Anthropic API key removed.')
            return None

        # Default action: set/replace the key.
        new_key = (request.POST.get('anthropic_api_key') or '').strip()
        if not new_key:
            return self.get_context(
                request,
                error='Paste your Anthropic API key, or click Remove to clear it.',
            )
        # Light validation — Anthropic keys start with ``sk-ant-`` but
        # we don't want to hard-fail on a valid key with a future
        # prefix change. Warn-then-store: refuse only obvious junk.
        if len(new_key) < 20:
            return self.get_context(
                request,
                error="That doesn't look like an Anthropic key. Keys are typically 100+ characters and start with 'sk-ant-'.",
            )

        if hasattr(user, 'anthropic_api_key'):
            user.anthropic_api_key = new_key
            user.save(update_fields=['anthropic_api_key_encrypted'])
            messages.success(request, 'Anthropic API key saved.')
        else:
            return self.get_context(
                request,
                error='This deployment does not store the Anthropic key locally. Set it on DockLabs.',
            )
        return None


def _encryption_configured() -> bool:
    """Whether encrypted-at-rest storage is available on this deployment.

    ``KeelUser.anthropic_api_key_encrypted`` is an ``EncryptedTextField``;
    saving a non-empty value raises ``ImproperlyConfigured`` at
    ``get_db_prep_save`` time when neither ``KEEL_ENCRYPTION_KEYS`` nor
    ``KEEL_ENCRYPTION_KEY`` is set. Probe up front so the panel can render
    an admin-facing fix-it message instead of 500ing on the first save.
    """
    from django.core.exceptions import ImproperlyConfigured

    try:
        from keel.security.encryption import get_fernet
        get_fernet()
        return True
    except ImproperlyConfigured:
        return False


def _keel_ai_url() -> str:
    """Build the URL the AI-panel mirror links to in suite mode."""
    issuer = getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or ''
    issuer = issuer.rstrip('/')
    return f'{issuer}/settings/ai/' if issuer else ''


class NotificationsPanel(SettingsPanel):
    """Per-user notification channel preferences.

    Rendered visible whenever `keel.notifications` is installed AND the
    deployment has a `KEEL_NOTIFICATION_PREFERENCE_MODEL` configured.
    Standalone deployments without notifications still see the empty
    settings page rather than a broken panel.
    """

    slug = 'notifications'
    label = 'Notifications'
    icon = 'bi-bell'
    order = 50  # Mid-priority; product-specific Profile/Account panels float above
    description = 'Channels you receive each notification type on'

    def is_visible(self, user) -> bool:
        if not super().is_visible(user):
            return False
        # Only show when the prefs model is configured.
        from keel.notifications.views import _get_preference_model
        return _get_preference_model() is not None

    def get_context(self, request) -> dict:
        from keel.notifications.registry import get_types_by_category
        from keel.notifications.views import _boswell_available, _get_preference_model

        PrefModel = _get_preference_model()
        product_prefixes = getattr(django_settings, 'KEEL_NOTIFICATION_CATEGORIES', None)
        types_by_category = get_types_by_category(for_user=request.user)
        if product_prefixes:
            types_by_category = {
                cat: types for cat, types in types_by_category.items()
                if any(cat.startswith(p) for p in product_prefixes)
            }

        try:
            user_prefs = {
                p.notification_type: p
                for p in PrefModel.objects.filter(user=request.user)
            }
        except Exception:
            logger.exception('settings.notifications: failed to load prefs')
            user_prefs = {}

        return {
            'categories': types_by_category,
            'preferences': user_prefs,
            'prefs_enabled': True,
            'sms_available': bool(
                getattr(django_settings, 'KEEL_SMS_BACKEND', None)
                or os.environ.get('KEEL_SMS_BACKEND')
            ),
            'user_has_phone': bool(getattr(request.user, 'phone', None)),
            'boswell_available': _boswell_available(types_by_category),
        }

    def post(self, request):
        from keel.notifications.registry import get_types_by_category
        from keel.notifications.views import _get_preference_model, _save_preferences

        PrefModel = _get_preference_model()
        if PrefModel is None:
            return None  # No-op success — nothing to save.

        product_prefixes = getattr(django_settings, 'KEEL_NOTIFICATION_CATEGORIES', None)
        types_by_category = get_types_by_category(for_user=request.user)
        if product_prefixes:
            types_by_category = {
                cat: types for cat, types in types_by_category.items()
                if any(cat.startswith(p) for p in product_prefixes)
            }
        _save_preferences(request, PrefModel, types_by_category)
        return None  # framework adds success message + redirects
