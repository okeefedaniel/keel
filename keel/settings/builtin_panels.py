"""Built-in settings panels shipped with keel itself.

Profile + Account panels handle identity surfaces (basic profile fields,
username change with live availability, email change with verification,
password change). The Notifications panel reuses
``keel.notifications.views.preferences`` rendering.

Identity edits are gated by deployment mode:

- **Standalone** (``KEEL_OIDC_CLIENT_ID`` unset): all panels are editable;
  the local KeelUser row is the source of truth.
- **Suite** (product, OIDC client of Keel): Profile panel renders
  read-only with a deep link to ``KEEL_OIDC_ISSUER/settings/profile/``;
  the Account panel is hidden entirely. Editing identity in-product
  would create drift between the JWT and the product's local row.
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

from keel.core.utils import is_keel_idp, is_suite_mode

from .base import SettingsPanel

logger = logging.getLogger(__name__)


def _identity_is_editable() -> bool:
    """Identity edits are allowed on standalone products and on Keel itself.

    Suite-mode products mirror identity from JWT claims and never write
    to it locally — see the panel docstrings for the rationale.
    """
    return is_keel_idp() or not is_suite_mode()


def _keel_profile_url() -> str:
    """Build the URL the Profile-panel mirror links to in suite mode."""
    issuer = getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or ''
    issuer = issuer.rstrip('/')
    return f'{issuer}/settings/profile/' if issuer else ''


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

        editable = _identity_is_editable()
        ctx = {
            'editable': editable,
            'keel_profile_url': _keel_profile_url(),
            'user': request.user,
            'avatar_error': avatar_error,
            # Surface the bytes ceiling to the template so client-side
            # validation matches the server-side ValueError code.
            'avatar_max_mb': 5,
        }
        if editable:
            ctx['form'] = form or ProfileForm(instance=request.user)
        return ctx

    def post(self, request):
        if not _identity_is_editable():
            messages.error(
                request,
                'Profile edits live on DockLabs. Use the link above to update.',
            )
            return self.get_context(request)

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
        # Suite-mode products have nothing to offer here. Hiding the
        # panel (rather than rendering a stub) keeps the left-rail nav
        # honest about where credential edits actually live.
        return _identity_is_editable()

    def get_context(self, request, *, username_form=None, email_form=None,
                    password_form=None):
        from keel.accounts.forms import EmailChangeForm, UsernameChangeForm

        return {
            'user': request.user,
            'username_form': username_form or UsernameChangeForm(user=request.user),
            'email_form': email_form or EmailChangeForm(user=request.user),
            'password_form': password_form or PasswordChangeForm(user=request.user),
            'username_check_url': '/keel/username-available/',
        }

    def post(self, request):
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
