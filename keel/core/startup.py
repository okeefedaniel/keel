"""Shared startup utilities for DockLabs products on Railway.

Provides ``ensure_site()`` to configure the django.contrib.sites Site object
required by allauth, and a ``run_startup()`` entry point for Railway's
start command.

Usage in product's startup.py or manage.py:
    from keel.core.startup import ensure_site
    ensure_site()

Or as a full Railway startup script:
    # Procfile / Railway start command:
    python -c "from keel.core.startup import run_startup; run_startup()" && gunicorn ...
"""
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


def ensure_site():
    """Ensure django.contrib.sites has the correct Site record.

    Required by allauth for email verification links and OAuth callbacks.
    Uses SITE_DOMAIN setting/env var and KEEL_PRODUCT_NAME for the name.
    """
    try:
        from django.contrib.sites.models import Site
    except Exception:
        logger.debug('django.contrib.sites not installed, skipping')
        return

    product_name = getattr(settings, 'KEEL_PRODUCT_NAME', 'DockLabs')
    default_domain = f'{product_name.lower()}.docklabs.ai'
    domain = (
        os.environ.get('SITE_DOMAIN')
        or getattr(settings, 'SITE_DOMAIN', None)
        or default_domain
    )

    site, created = Site.objects.update_or_create(
        id=getattr(settings, 'SITE_ID', 1),
        defaults={'domain': domain, 'name': product_name},
    )
    action = 'created' if created else 'updated'
    logger.info('Site %s: %s (%s)', action, site.domain, site.name)


def run_startup(extra_commands=None):
    """Run standard Railway startup tasks: migrate, collectstatic, ensure_site.

    Args:
        extra_commands: Optional list of management command arg lists to run
            after the standard commands (e.g., [['seed_keel_users']]).
    """
    import subprocess
    import sys

    import django
    django.setup()

    commands = [
        [sys.executable, 'manage.py', 'migrate', '--noinput'],
        [sys.executable, 'manage.py', 'collectstatic', '--noinput'],
    ]

    # Seed demo users when DEMO_MODE is enabled
    if os.environ.get('DEMO_MODE', 'False').lower() in ('true', '1', 'yes'):
        commands.append([sys.executable, 'manage.py', 'seed_keel_users'])

    if extra_commands:
        for cmd_args in extra_commands:
            commands.append([sys.executable, 'manage.py'] + cmd_args)

    for cmd in commands:
        label = ' '.join(cmd)
        print(f'Running: {label}', flush=True)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f'FATAL: Command failed with exit code {result.returncode}', flush=True)
            sys.exit(result.returncode)

    ensure_site()
    print('Startup complete', flush=True)
