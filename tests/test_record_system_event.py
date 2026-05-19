"""Tests for ``keel.activity.services.record_system_event`` (keel v0.47.0).

Under Approach D, system events write to Activity ONLY — NOT to AuditLog.
The helper enforces:
- status MUST be one of ('ok', 'warn', 'failed', 'errored') — typos raise.
- KEEL_ACTIVITY_MODEL unset → fail-soft, log, return None (lets products
  mid-rollout import this module without crashing).

Full happy-path emission to a real Activity table is integration-tested
via the broader keel suite that has the test models migrated. These unit
tests cover the contract guards only.
"""
import pytest


def test_record_system_event_rejects_invalid_status():
    """status must be one of the four recognized values — typos raise immediately
    rather than producing un-categorizable rows."""
    from keel.activity.services import record_system_event

    with pytest.raises(ValueError, match='status must be one of'):
        record_system_event(
            verb='test.event',
            summary='whatever',
            status='success',  # not in the allowlist; common typo
        )

    with pytest.raises(ValueError, match='status must be one of'):
        record_system_event(
            verb='test.event',
            summary='whatever',
            status='',  # empty string is not the OK default
        )


def test_record_system_event_accepts_each_valid_status(settings):
    """All four allowed statuses pass the validation gate.

    Use settings='' for KEEL_ACTIVITY_MODEL so the helper fail-softs to None
    rather than trying to write to the DB (which would require migrations).
    """
    from keel.activity.services import record_system_event

    settings.KEEL_ACTIVITY_MODEL = ''  # force fail-soft path

    for status in ('ok', 'warn', 'failed', 'errored'):
        result = record_system_event(
            verb='test.event',
            summary=f'event with status={status}',
            status=status,
        )
        # Fail-soft returns None when KEEL_ACTIVITY_MODEL is unset.
        assert result is None


def test_record_system_event_fail_soft_when_activity_model_unset(settings):
    """A product that imports this module without configuring KEEL_ACTIVITY_MODEL
    gets a warning and a None return — not a crash. The CommandRun row from
    @scheduled_job still captures the cron's lifecycle as minimum-viable
    observability."""
    from keel.activity.services import record_system_event

    settings.KEEL_ACTIVITY_MODEL = ''
    assert record_system_event(verb='test.x', summary='msg') is None
