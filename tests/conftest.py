"""Pytest configuration for the Keel test suite.

Runs under the existing ``keel_site`` Django settings so tests exercise
the same IdP/OIDC configuration as production. Individual test files
remain free to override settings per test via
``django.test.override_settings``.
"""
import os

import django


def pytest_configure(config):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'keel_site.settings')
    # Keel's keel_site.settings raises when DJANGO_SECRET_KEY is unset
    # outside DEBUG. Force a debug key for the test run.
    os.environ.setdefault('DJANGO_DEBUG', '1')
    os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-secret-key-do-not-use-in-prod')
    django.setup()
