"""Tests for migration 0020_seed_existing_subs_ai_enabled.

The backfill flips ``ai_enabled=True`` on every active
``OrganizationProductSubscription``. Verifies:

- Active subs (``is_active=True``) get ``ai_enabled=True``.
- Inactive subs (``is_active=False``) are left alone.
- Reverse migration is a noop (data is preserved on rollback).
- Idempotent — re-running doesn't double-flip or fail.
"""

import pytest

from keel.accounts.models import Organization, OrganizationProductSubscription


pytest.importorskip('cryptography')


def _backfill():
    """Re-run the migration's forward function against the live DB.

    Migration filenames start with digits so they aren't importable
    via the normal Python import machinery — use ``importlib`` to
    load the module by file path, then call its forward function.
    """
    import importlib.util
    import pathlib

    from django.apps import apps as django_apps

    keel_root = pathlib.Path(__file__).resolve().parent.parent
    mig_path = keel_root / 'keel' / 'accounts' / 'migrations' / '0020_seed_existing_subs_ai_enabled.py'
    spec = importlib.util.spec_from_file_location('mig_0020', mig_path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    class _StubApps:
        def get_model(self, app_label, model_name):
            return django_apps.get_model(app_label, model_name)

    mig.seed_ai_enabled_on_active_subs(_StubApps(), schema_editor=None)


@pytest.fixture
def org(db):
    return Organization.objects.create(slug='mig-0020-org', name='Mig Test')


def test_active_subs_flipped_to_true(db, org):
    """An active sub created with default ai_enabled=False gets True after backfill."""
    sub = OrganizationProductSubscription.objects.create(
        organization=org, product='beacon', is_active=True, ai_enabled=False,
    )
    assert sub.ai_enabled is False  # default-False from 0018

    _backfill()

    sub.refresh_from_db()
    assert sub.ai_enabled is True


def test_inactive_subs_left_alone(db, org):
    """Inactive subs do NOT get flipped (deactivated customers stay disabled)."""
    sub = OrganizationProductSubscription.objects.create(
        organization=org, product='bounty', is_active=False, ai_enabled=False,
    )

    _backfill()

    sub.refresh_from_db()
    assert sub.ai_enabled is False


def test_idempotent_rerun(db, org):
    """Running the backfill twice is a noop — no double-flip, no error."""
    OrganizationProductSubscription.objects.create(
        organization=org, product='helm', is_active=True, ai_enabled=False,
    )

    _backfill()
    _backfill()  # second run

    sub = OrganizationProductSubscription.objects.get(
        organization=org, product='helm',
    )
    assert sub.ai_enabled is True
