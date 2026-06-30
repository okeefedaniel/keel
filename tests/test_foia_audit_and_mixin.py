"""Tests for `manage.py foia_audit` and `keel.foia.mixins.FOIAExportMixin`.

These two pieces are documented in keel's CLAUDE.md / README ("Validate with:
`python manage.py foia_audit`" and "Add export buttons to detail views via
`FOIAExportMixin`") but had no implementation on `main` until this change.

`foia_audit` pins:
- Runs against keel_site and emits one result per global check + one per product.
- `--json` produces a parseable envelope with a top-level `passed` boolean.
- The KEEL_FOIA_EXPORT_MODEL check flips PASS/FAIL with the setting.
- A product with a registered exportable type reports PASS (not the WARN).
- `--fail-on-error` raises SystemExit(1) when any check FAILs.

`FOIAExportMixin` pins:
- Injects `foia_record_type` / `foia_product_name` into the view context.
"""
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from keel.foia.export import foia_export_registry
from keel.foia.mixins import FOIAExportListMixin, FOIAExportMixin


# A real model path satisfies the "is set" check (it only tests truthiness).
_EXPORT_MODEL = 'keel_accounts.AuditLog'


@pytest.fixture
def clean_registry():
    """Snapshot and restore the module-level export registry.

    The registry is a process-wide singleton; tests that register types
    must not leak entries into sibling tests.
    """
    saved = dict(foia_export_registry._registry)
    try:
        yield foia_export_registry
    finally:
        foia_export_registry._registry = saved


def _run_json(*args):
    """Run foia_audit --json and return the parsed envelope."""
    out = StringIO()
    call_command('foia_audit', '--json', *args, stdout=out)
    return json.loads(out.getvalue())


pytestmark = pytest.mark.django_db


def test_json_envelope_shape():
    payload = _run_json()
    assert 'foia_audit' in payload
    assert 'passed' in payload
    assert isinstance(payload['foia_audit'], list)
    assert payload['foia_audit'], 'expected at least the global checks'
    for result in payload['foia_audit']:
        assert set(result) >= {'check', 'status'}
        assert result['status'] in {'PASS', 'WARN', 'FAIL'}


@override_settings(KEEL_FOIA_EXPORT_MODEL=_EXPORT_MODEL)
def test_export_model_check_passes_when_set():
    payload = _run_json()
    export_check = next(
        r for r in payload['foia_audit']
        if 'KEEL_FOIA_EXPORT_MODEL' in r['check']
    )
    assert export_check['status'] == 'PASS'


@override_settings(KEEL_FOIA_EXPORT_MODEL=None)
def test_export_model_check_fails_when_unset():
    payload = _run_json()
    export_check = next(
        r for r in payload['foia_audit']
        if 'KEEL_FOIA_EXPORT_MODEL' in r['check']
    )
    assert export_check['status'] == 'FAIL'
    assert payload['passed'] is False


def test_registered_product_reports_pass(clean_registry):
    clean_registry.register(
        product='beacon',
        record_type='interaction',
        queryset_fn=lambda: None,
        serializer_fn=lambda obj: None,
        display_name='Interaction',
    )
    payload = _run_json()
    beacon_check = next(
        r for r in payload['foia_audit']
        if r['check'].startswith('beacon:')
    )
    assert beacon_check['status'] == 'PASS'
    assert 'Interaction' in beacon_check['detail']


def test_unregistered_product_reports_warn():
    payload = _run_json()
    # Purser registers nothing in keel_site, so it should warn.
    purser_check = next(
        r for r in payload['foia_audit']
        if r['check'].startswith('purser:')
    )
    assert purser_check['status'] == 'WARN'


@override_settings(KEEL_FOIA_EXPORT_MODEL=None)
def test_fail_on_error_exits_nonzero():
    # KEEL_FOIA_EXPORT_MODEL unset → a FAIL exists → SystemExit(1).
    with pytest.raises(SystemExit) as exc:
        call_command('foia_audit', '--fail-on-error', stdout=StringIO())
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# FOIAExportMixin / FOIAExportListMixin
# ---------------------------------------------------------------------------

class _StubBase:
    """Minimal stand-in for Django's view base get_context_data."""

    def get_context_data(self, **kwargs):
        return dict(kwargs)


def test_export_mixin_injects_context():
    class _DetailView(FOIAExportMixin, _StubBase):
        foia_record_type = 'testimony'
        foia_product_name = 'lookout'

    ctx = _DetailView().get_context_data()
    assert ctx['foia_record_type'] == 'testimony'
    assert ctx['foia_product_name'] == 'lookout'


def test_list_mixin_injects_bulk_flag():
    class _ListView(FOIAExportListMixin, _StubBase):
        foia_record_type = 'interaction'
        foia_product_name = 'beacon'

    ctx = _ListView().get_context_data()
    assert ctx['foia_record_type'] == 'interaction'
    assert ctx['foia_product_name'] == 'beacon'
    assert ctx['foia_bulk_export'] is True
