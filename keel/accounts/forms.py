"""Shared authentication forms for all DockLabs products.

Usage in product's core/forms.py:
    from keel.accounts.forms import LoginForm  # noqa: F401
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _


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
