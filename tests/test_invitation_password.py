"""accept_invitation must run AUTH_PASSWORD_VALIDATORS before create_user."""
from __future__ import annotations

import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import override_settings

from keel.accounts.models import KeelUser


PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]


@override_settings(AUTH_PASSWORD_VALIDATORS=PASSWORD_VALIDATORS)
def test_short_password_rejected():
    with pytest.raises(ValidationError):
        validate_password('1', user=KeelUser(username='x', email='x@example.com'))


@override_settings(AUTH_PASSWORD_VALIDATORS=PASSWORD_VALIDATORS)
def test_strong_password_accepted():
    # Should not raise.
    validate_password('correcthorsebatterystaple-9817', user=KeelUser(
        username='x', email='x@example.com',
    ))
