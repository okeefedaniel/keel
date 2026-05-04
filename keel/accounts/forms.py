"""Shared authentication & profile forms for all DockLabs products.

Usage in product's core/forms.py:
    from keel.accounts.forms import LoginForm  # noqa: F401
"""
import re
import zoneinfo

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from .models import KeelUser


# Username validation rule used by both the live-availability endpoint
# and the rename form. Lowercased ASCII, 3–32 chars, can't start with
# dash/underscore. Centralized here so the JS, the API, and the form
# can never disagree on what's valid.
USERNAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{2,31}$')

# Reserved usernames that are never available regardless of DB state.
# Includes route prefixes that would shadow product URLs and admin-tier
# accounts whose names should never be reusable.
RESERVED_USERNAMES = frozenset({
    'admin', 'administrator', 'system', 'systemadmin', 'system_admin',
    'root', 'superuser', 'support', 'help', 'info', 'noreply', 'no-reply',
    'docklabs', 'keel', 'dokadmin',
    'api', 'auth', 'login', 'logout', 'signup', 'register',
    'oauth', 'oidc', 'sso', 'me', 'self', 'null', 'undefined',
})


def validate_username_format(value: str) -> str | None:
    """Return an error code, or None when *value* is well-formed.

    Codes match the JS contract for `username-check.js`:
      - ``invalid_format`` — fails the regex
      - ``reserved``       — listed in RESERVED_USERNAMES
      - None               — looks good (still must be uniqueness-checked)
    """
    candidate = (value or '').strip().lower()
    if not USERNAME_RE.match(candidate):
        return 'invalid_format'
    if candidate in RESERVED_USERNAMES:
        return 'reserved'
    return None


class LoginForm(AuthenticationForm):
    """Shared DockLabs login form — styled consistently across all products.

    Accepts either a username or email address in the username field.
    """

    username = forms.CharField(
        label=_('Username or email'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Username or email'),
            'autofocus': True,
        }),
    )
    password = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('Password'),
        }),
    )


# ---------------------------------------------------------------------------
# Profile forms — used by keel.settings.builtin_panels.ProfilePanel
# ---------------------------------------------------------------------------
def _timezone_choices():
    """IANA timezone names, sorted, prefixed by a blank "(detect from browser)".

    Returns a list of (value, label) tuples suitable for ChoiceField.
    """
    zones = sorted(zoneinfo.available_timezones())
    return [('', _('— Auto-detect from browser —'))] + [(z, z) for z in zones]


# Locale list intentionally short — we don't ship translations for most of
# these, but the field captures the user's preferred display language so a
# future i18n pass has data to read. Alphabetical by English label.
LOCALE_CHOICES = [
    ('', _('— System default —')),
    ('en', 'English'),
    ('en-US', 'English (United States)'),
    ('en-GB', 'English (United Kingdom)'),
    ('es', 'Español'),
    ('fr', 'Français'),
    ('de', 'Deutsch'),
    ('pt', 'Português'),
    ('zh-CN', '中文 (简体)'),
]


class ProfileForm(forms.ModelForm):
    """Edit a user's basic profile fields.

    Excludes username, email, and password — those have dedicated forms
    with extra side effects (verification, session invalidation, etc.).
    """

    timezone = forms.ChoiceField(
        choices=_timezone_choices,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    locale = forms.ChoiceField(
        choices=LOCALE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = KeelUser
        fields = ('first_name', 'last_name', 'title', 'phone', 'timezone', 'locale')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('e.g. Program Officer'),
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('+1 555 123 4567'),
                'inputmode': 'tel',
            }),
        }


class UsernameChangeForm(forms.Form):
    """Rename the current user's username.

    Validation runs the same `validate_username_format` + uniqueness
    checks as the live-availability endpoint, so the form rejects the
    same inputs the JS marked red.
    """

    username = forms.CharField(
        label=_('New username'),
        max_length=32,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'off',
            'autocapitalize': 'off',
            'spellcheck': 'false',
            'data-username-check': 'true',
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_username(self):
        candidate = (self.cleaned_data.get('username') or '').strip().lower()
        err = validate_username_format(candidate)
        if err == 'invalid_format':
            raise forms.ValidationError(_(
                'Usernames must be 3–32 characters, lowercase letters, '
                'numbers, dash or underscore, and start with a letter or number.'
            ))
        if err == 'reserved':
            raise forms.ValidationError(_('This username is reserved.'))
        if self.user and candidate == self.user.username:
            raise forms.ValidationError(_('That is already your username.'))
        # Case-insensitive uniqueness — ``KeelUser.username`` is stored
        # case-sensitive but allauth treats them case-insensitively at
        # login time, and we want to forbid `Dan` if `dan` is taken.
        existing = KeelUser.objects.filter(username__iexact=candidate)
        if self.user:
            existing = existing.exclude(pk=self.user.pk)
        if existing.exists():
            raise forms.ValidationError(_('That username is already taken.'))
        return candidate


class EmailChangeForm(forms.Form):
    """Request a new email address.

    The form does NOT mutate ``user.email`` directly. The view sends a
    confirmation email via allauth's ``EmailAddress`` model, and the new
    address only becomes primary when the user clicks the link.
    """

    email = forms.EmailField(
        label=_('New email address'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'autocomplete': 'email',
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_email(self):
        candidate = (self.cleaned_data.get('email') or '').strip().lower()
        if self.user and candidate == (self.user.email or '').lower():
            raise forms.ValidationError(_('That is already your email.'))
        existing = KeelUser.objects.filter(email__iexact=candidate)
        if self.user:
            existing = existing.exclude(pk=self.user.pk)
        if existing.exists():
            raise forms.ValidationError(_('That email is already in use.'))
        return candidate
