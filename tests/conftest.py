"""Pytest configuration for the Keel test suite.

Runs under ``tests.settings``, which is the production ``keel_site``
IdP/OIDC configuration plus the allauth apps a consuming product installs
via the ``[sso]`` extra. Individual test files remain free to override
settings per test via ``django.test.override_settings``.
"""
import os

import django


def pytest_configure(config):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.settings')
    # Keel's keel_site.settings now refuses to start without SECRET_KEY
    # outside DEBUG. Force DEBUG + a fixed key for the test run.
    os.environ.setdefault('DEBUG', '1')
    os.environ.setdefault('SECRET_KEY', 'test-only-secret-key-do-not-use-in-prod')
    django.setup()
