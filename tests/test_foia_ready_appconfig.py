"""Tests for `keel.foia.apps.FOIAReadyAppConfig`.

CLAUDE.md documents this as the base AppConfig products subclass to get
"automatic validation" of FOIA readiness, but `main` shipped without it.

Pins:
- A subclass that forgets `register_foia_exports()` raises NotImplementedError.
- `ready()` calls `register_foia_exports()` (types land in the registry).
- Validation is non-fatal: a fully-misconfigured product still completes
  `ready()`, but logs warnings for the missing export model and the empty
  registry.
- A correctly-wired product logs no FOIA warnings.
"""
import logging

import keel.foia as foia_module
import pytest
from django.test import override_settings

from keel.foia.apps import FOIAReadyAppConfig
from keel.foia.export import foia_export_registry


@pytest.fixture
def clean_registry():
    """Snapshot/restore the process-wide export registry singleton."""
    saved = dict(foia_export_registry._registry)
    try:
        yield foia_export_registry
    finally:
        foia_export_registry._registry = saved


def _make(cfg_cls):
    """Instantiate an AppConfig subclass without registering it in apps."""
    return cfg_cls('keel.foia', foia_module)


def test_missing_register_raises():
    class Bare(FOIAReadyAppConfig):
        foia_product_name = 'beacon'

    with pytest.raises(NotImplementedError):
        _make(Bare).register_foia_exports()


@override_settings(KEEL_FOIA_EXPORT_MODEL='keel_accounts.AuditLog')
def test_ready_registers_types(clean_registry):
    class Wired(FOIAReadyAppConfig):
        foia_product_name = 'beacon'

        def register_foia_exports(self):
            foia_export_registry.register(
                product='beacon',
                record_type='interaction',
                queryset_fn=lambda: None,
                serializer_fn=lambda obj: None,
                display_name='Interaction',
            )

    _make(Wired).ready()
    types = foia_export_registry.get_exportable_types(product='beacon')
    assert [t.record_type for t in types] == ['interaction']


@override_settings(KEEL_FOIA_EXPORT_MODEL='keel_accounts.AuditLog')
def test_wired_product_logs_no_warnings(clean_registry, caplog):
    class Wired(FOIAReadyAppConfig):
        foia_product_name = 'beacon'

        def register_foia_exports(self):
            foia_export_registry.register(
                product='beacon', record_type='interaction',
                queryset_fn=lambda: None, serializer_fn=lambda obj: None,
            )

    with caplog.at_level(logging.WARNING, logger='keel.foia.apps'):
        _make(Wired).ready()
    assert not [r for r in caplog.records if r.name == 'keel.foia.apps']


@override_settings(KEEL_FOIA_EXPORT_MODEL=None)
def test_misconfigured_product_warns_but_does_not_raise(clean_registry, caplog):
    class Empty(FOIAReadyAppConfig):
        foia_product_name = 'beacon'

        def register_foia_exports(self):
            pass  # registers nothing

    with caplog.at_level(logging.WARNING, logger='keel.foia.apps'):
        _make(Empty).ready()  # must NOT raise

    messages = [r.getMessage() for r in caplog.records if r.name == 'keel.foia.apps']
    assert any('KEEL_FOIA_EXPORT_MODEL is not set' in m for m in messages)
    assert any('no registered exportable types' in m for m in messages)
