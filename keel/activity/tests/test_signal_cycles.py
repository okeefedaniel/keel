"""Tests for the audit-exclusion list that prevents recursive auditing.

The audit → activity → notification chain WOULD recurse if products inadvertently
register Activity / Watcher / Notification / NotificationLog / AuditLog itself for
auto-audit. The builtin exclusion list in ``keel.core.audit_signals`` defends against
this — these tests pin the contract.
"""
from keel.core import audit_signals


def test_builtin_excluded_models_includes_critical_layers():
    """Pin the contract: every layer in audit → activity → notification is excluded."""
    excluded = audit_signals._BUILTIN_AUDIT_EXCLUDED_MODELS
    # Activity / Watcher
    assert 'keel_activity.activity' in excluded
    assert 'keel_activity.watcher' in excluded
    # Notification stack
    assert 'keel_notifications.notification' in excluded
    assert 'keel_notifications.notificationlog' in excluded
    assert 'keel_notifications.notificationpreference' in excluded
    # AuditLog itself
    assert 'core.auditlog' in excluded


def test_is_audit_excluded_matches_builtin():
    assert audit_signals._is_audit_excluded('keel_activity.activity') is True
    assert audit_signals._is_audit_excluded('keel_activity.watcher') is True
    assert audit_signals._is_audit_excluded('core.auditlog') is True


def test_is_audit_excluded_case_insensitive():
    assert audit_signals._is_audit_excluded('KEEL_ACTIVITY.ACTIVITY') is True
    assert audit_signals._is_audit_excluded('Core.AuditLog') is True


def test_is_audit_excluded_extends_via_settings(settings):
    settings.KEEL_AUDIT_EXCLUDED_MODELS = ['myapp.NoisyModel']
    assert audit_signals._is_audit_excluded('myapp.noisymodel') is True
    assert audit_signals._is_audit_excluded('myapp.othermodel') is False


def test_is_audit_excluded_returns_false_for_normal_model():
    assert audit_signals._is_audit_excluded('keel_accounts.keeluser') is False
    assert audit_signals._is_audit_excluded('signatures.signingstep') is False
