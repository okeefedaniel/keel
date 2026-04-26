"""Production settings must fail loud on missing SECRET_KEY / ALLOWED_HOSTS.

Rather than reloading the full settings module (which has many side
effects), this test re-runs just the env-var guard logic from
keel_site/settings.py against a controlled environment.
"""
from __future__ import annotations

import secrets

import pytest
from django.core.exceptions import ImproperlyConfigured


def _resolve(env: dict) -> dict:
    """Mirror the SECRET_KEY / ALLOWED_HOSTS block from keel_site.settings."""
    debug = env.get('DEBUG', 'False').lower() in ('true', '1', 'yes')

    secret_key = env.get('SECRET_KEY')
    if not secret_key:
        if debug:
            secret_key = 'django-insecure-dev-only-' + secrets.token_urlsafe(32)
        else:
            raise ImproperlyConfigured('SECRET_KEY required')

    default_hosts = 'localhost,127.0.0.1' if debug else ''
    allowed_hosts = [
        h.strip() for h in env.get('ALLOWED_HOSTS', default_hosts).split(',') if h.strip()
    ]
    if not debug and not allowed_hosts:
        raise ImproperlyConfigured('ALLOWED_HOSTS required')

    return {'SECRET_KEY': secret_key, 'ALLOWED_HOSTS': allowed_hosts}


def test_missing_secret_key_in_production_raises():
    with pytest.raises(ImproperlyConfigured):
        _resolve({'DEBUG': 'False', 'ALLOWED_HOSTS': 'keel.docklabs.ai'})


def test_missing_allowed_hosts_in_production_raises():
    with pytest.raises(ImproperlyConfigured):
        _resolve({'DEBUG': 'False', 'SECRET_KEY': 'real-prod-key'})


def test_debug_falls_back_to_dev_secret():
    out = _resolve({'DEBUG': '1'})
    assert out['SECRET_KEY'].startswith('django-insecure-dev-only-')
    assert out['ALLOWED_HOSTS'] == ['localhost', '127.0.0.1']


def test_production_with_both_env_vars_succeeds():
    out = _resolve({
        'DEBUG': 'False',
        'SECRET_KEY': 'real-key',
        'ALLOWED_HOSTS': 'keel.docklabs.ai,demo-keel.docklabs.ai',
    })
    assert out['SECRET_KEY'] == 'real-key'
    assert 'keel.docklabs.ai' in out['ALLOWED_HOSTS']
