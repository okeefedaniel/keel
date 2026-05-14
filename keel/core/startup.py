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
        # Always ensure the dokadmin bootstrap superuser exists. Required
        # for SSO — Keel's JWT carries preferred_username=dokadmin and each
        # product's adapter matches that against the local username before
        # falling back to email. Without dokadmin, SSO fails with "Signup
        # currently closed" on fresh deployments. Idempotent.
        [sys.executable, 'manage.py', 'ensure_dokadmin'],
    ]

    # Seed the full demo-user set (per-product roles) only in DEMO_MODE.
    # dokadmin is handled above unconditionally.
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
    verify_canonical_css()
    print('Startup complete', flush=True)


# Markers that the canonical suite stylesheet MUST contain for the deploy
# to be considered healthy. If `.dl-status-dot` is missing from the
# collected `docklabs-v2.css`, the product is shipping the pre-PR-#20
# version of the keel wheel (the pip-cache trap that bit Bounty + Yeoman
# on 2026-05-13). Better to fail the deploy loud than serve stale CSS.
_CANONICAL_CSS_MARKERS = (
    '.dl-status-dot {',
    '.dl-status-pill {',
)


def verify_canonical_css():
    """Assert that collectstatic produced a `docklabs-v2.css` containing
    every canonical class the suite expects. Catches stale keel-wheel
    deploys that silently regress the dot+text status pattern — see the
    'PR-after-tag keel releases hit the pip-cache trap' note in
    keel/CLAUDE.md.

    Skipped (with a one-line warning) if STATIC_ROOT isn't configured,
    or if the file doesn't exist after collectstatic — those cases are
    legitimate (local dev, products that don't yet use docklabs-v2). The
    check only fires when the file IS present and we can affirmatively
    say "this product serves docklabs-v2.css but it's the wrong build."
    """
    import sys

    static_root = getattr(settings, 'STATIC_ROOT', None)
    if not static_root:
        print('verify_canonical_css: STATIC_ROOT not configured, skipping', flush=True)
        return

    css_path = os.path.join(str(static_root), 'css', 'docklabs-v2.css')
    if not os.path.exists(css_path):
        print(
            f'verify_canonical_css: {css_path} not found, skipping '
            '(product may not use docklabs-v2)',
            flush=True,
        )
        return

    try:
        with open(css_path, 'r', encoding='utf-8') as fh:
            content = fh.read()
    except OSError as exc:
        print(f'verify_canonical_css: read failed ({exc}), skipping', flush=True)
        return

    missing = [m for m in _CANONICAL_CSS_MARKERS if m not in content]
    if missing:
        size_kb = len(content) // 1024
        print(
            f'FATAL: collected docklabs-v2.css ({size_kb} KB) is missing '
            f'canonical markers: {missing}. This is the pip-cache trap — '
            'the cached keel wheel pre-dates the suite-design CSS rules. '
            'Cut a no-code-change keel patch release (bump '
            'keel/__init__.py + pyproject.toml) and bump the product pin '
            'to invalidate the cache. See keel/CLAUDE.md → "PR-after-tag '
            'keel releases hit the pip-cache trap".',
            flush=True,
        )
        sys.exit(1)

    print(
        f'verify_canonical_css: docklabs-v2.css has all canonical markers '
        f'({len(_CANONICAL_CSS_MARKERS)} checked)',
        flush=True,
    )
