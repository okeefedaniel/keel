"""Tests for ``keel.core.middleware.audit_context`` (keel v0.47.0).

The audit_context context manager is the escape hatch for the v0.46.3 gate:
async workers / shell sessions / data migrations doing user-attributable
work can wrap their mutations in ``with audit_context(user=...)`` so the
auto-audit signal handlers attribute the resulting rows correctly. Without
the context manager, the gate causes non-request mutations to skip audit
entirely.
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_audit_context():
    from keel.core.audit_signals import set_audit_context
    set_audit_context(user=None, ip_address=None)
    yield
    set_audit_context(user=None, ip_address=None)


def test_audit_context_sets_thread_local_user():
    from keel.core.middleware import audit_context
    from keel.core.audit_signals import get_audit_context

    class _FakeUser:
        pk = 42
        is_authenticated = True

    user = _FakeUser()
    # Before the block: thread-local is empty (per autouse fixture).
    assert get_audit_context() == (None, None)

    with audit_context(user=user, ip='10.0.0.1'):
        in_user, in_ip = get_audit_context()
        assert in_user is user
        assert in_ip == '10.0.0.1'

    # After the block: thread-local restored to prior state.
    assert get_audit_context() == (None, None)


def test_audit_context_restores_prior_value_on_exit():
    """Nested calls and prior-set values must be preserved on exit."""
    from keel.core.middleware import audit_context
    from keel.core.audit_signals import set_audit_context, get_audit_context

    class _U:
        def __init__(self, pk):
            self.pk = pk
            self.is_authenticated = True

    outer = _U(pk=1)
    inner = _U(pk=2)

    # Simulate a request-driven outer context (set by AuditMiddleware).
    set_audit_context(user=outer, ip_address='1.1.1.1')

    with audit_context(user=inner, ip='2.2.2.2'):
        u, ip = get_audit_context()
        assert u is inner
        assert ip == '2.2.2.2'

    # Exit must restore the outer context, not clear it.
    u, ip = get_audit_context()
    assert u is outer
    assert ip == '1.1.1.1'


def test_audit_context_restores_on_exception():
    """An exception inside the block must still restore prior state.

    This matches AuditMiddleware's try/finally invariant — without it, a
    raising async task would leave its user in thread-local and contaminate
    the next caller on the same thread.
    """
    from keel.core.middleware import audit_context
    from keel.core.audit_signals import get_audit_context

    class _U:
        pk = 99
        is_authenticated = True

    with pytest.raises(RuntimeError, match='simulated'):
        with audit_context(user=_U(), ip='9.9.9.9'):
            raise RuntimeError('simulated work failure')

    # Even though the block raised, thread-local must be clean.
    assert get_audit_context() == (None, None)
