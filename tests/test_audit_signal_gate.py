"""Tests for the audit-signal user gate (keel v0.46.3).

The auto-audit ``post_save`` / ``post_delete`` signal handlers must early-return
when the thread-local audit context has ``user=None``. This stops cron jobs,
management commands, data migrations, and async workers (anything outside an
authenticated request context) from writing NULL-user rows into the audit log.

Symptom this gate fixes: bounty's ``bounty_core_auditlog`` table grew to 2368 MB
(98% of the DB) with 1.27M rows, 99.996% of which were cron-driven
``FederalOpportunity`` updates with ``user_id IS NULL``.

The gate is the structural answer: AuditLog is for user accountability. System
events with material effects belong in Activity (Track B), not AuditLog.

See ``~/.claude/plans/audit-activity-notifications-rethink.md`` for the full
architectural rationale.
"""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_audit_context():
    """Clear thread-local audit context before AND after each test.

    Otherwise a prior test that set a user in thread-local would bleed into
    these tests' assertions.
    """
    from keel.core.audit_signals import set_audit_context
    set_audit_context(user=None, ip_address=None)
    yield
    set_audit_context(user=None, ip_address=None)


class _FakeMeta:
    """Minimal ``_meta`` shape for the signal handler's model_label compute."""
    def __init__(self, app_label, model_name):
        self.app_label = app_label
        # _on_save uses sender.__name__, not sender._meta.model_name; but include
        # both for completeness so future code can switch transparently.
        self.model_name = model_name


class _FakeSender:
    """Pretends to be a Django model class for the signal handler.

    ``_on_save`` reads ``sender._meta.app_label`` and ``sender.__name__`` to
    compute the model_label key for the registry lookup. Nothing else on the
    sender is touched by the gate logic.
    """
    __name__ = 'TestModel'
    _meta = _FakeMeta(app_label='testapp', model_name='testmodel')


class _FakeInstanceMeta:
    """``_meta`` shape for ``_compute_changes`` — empty field list keeps it cheap."""
    concrete_fields = ()


class _FakeInstance:
    """Minimal instance shape.

    The gate fires before any field inspection, but the write path runs
    ``_compute_changes(instance, skip_fields)`` which iterates
    ``instance._meta.concrete_fields``. An empty tuple is the cheapest valid
    iterable that exercises the same code path without needing real ORM fields.
    """
    pk = 1
    _meta = _FakeInstanceMeta()

    def __str__(self):
        return 'fake instance'


@pytest.fixture
def registered_model():
    """Register the fake model so the registry lookup succeeds.

    Without this, _on_save returns early for an unregistered model and we
    can't tell the gate from the unregistered case.
    """
    from keel.core.audit_signals import _registry, AuditedModel
    _registry['testapp.TestModel'] = AuditedModel(
        model_label='testapp.TestModel',
        display_name='Test Model',
        skip_fields=set(),
    )
    yield
    _registry.pop('testapp.TestModel', None)


def test_on_save_skipped_when_no_user_in_context(registered_model):
    """Cron/management-command path: thread-local user is None → no audit row."""
    from keel.core.audit_signals import _on_save

    with patch('keel.core.audit.log_audit') as mock_log_audit:
        _on_save(sender=_FakeSender, instance=_FakeInstance(), created=True)

    assert not mock_log_audit.called, (
        'Audit signal must NOT write a row when thread-local user is None '
        '(cron / management / migration context). This is the gate that '
        'stops bounty-style audit-log bloat.'
    )


def test_on_delete_skipped_when_no_user_in_context(registered_model):
    """Same gate applies to deletes — cron-driven deletes are not user actions."""
    from keel.core.audit_signals import _on_delete

    with patch('keel.core.audit.log_audit') as mock_log_audit:
        _on_delete(sender=_FakeSender, instance=_FakeInstance())

    assert not mock_log_audit.called, (
        'Audit signal must NOT write a delete row when thread-local user is None.'
    )


# Note on coverage: the "user IS set → audit row written" path is already
# exercised by ``test_audit_middleware.py`` and the broader keel integration
# suite. We intentionally do not duplicate it here — attempting to mock far
# enough up the stack to isolate just _on_save's write path requires DB
# migrations that aren't available in this lightweight test setup. The two
# gate-skip tests above are the new behavior under test (keel v0.46.3); the
# write path is unchanged from prior versions.
