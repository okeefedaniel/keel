"""Pytest configuration for keel.activity tests.

Mirrors ``keel/tests/conftest.py``: sets up Django before any test module is imported,
so ``from keel.activity.services import ContentType`` works at collection time without
requiring callers to set DJANGO_SETTINGS_MODULE in their environment.
"""
import os

import django


def pytest_configure(config):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'keel_site.settings')
    os.environ.setdefault('DEBUG', '1')
    os.environ.setdefault('SECRET_KEY', 'test-only-secret-key-do-not-use-in-prod')
    django.setup()
