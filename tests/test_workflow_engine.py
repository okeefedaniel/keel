"""Tests for ``keel.core.workflow.WorkflowEngine``.

Pins the role-check and validation behaviour. Every product with a
status-bearing model depends on these invariants.
"""
import pytest

from django.core.exceptions import PermissionDenied, ValidationError

from keel.core.workflow import Transition, WorkflowEngine


class _FakeUser:
    def __init__(self, role='', **props):
        self.role = role
        self.is_authenticated = True
        for k, v in props.items():
            setattr(self, k, v)


def _build_engine():
    return WorkflowEngine([
        Transition('draft', 'submitted', roles=['any'], label='Submit'),
        Transition('submitted', 'approved', roles=['foia_manager'], label='Approve'),
        Transition('submitted', 'rejected', roles=['foia_manager'],
                   label='Reject', require_comment=True),
        Transition('approved', 'closed', roles=['system_admin'], label='Close'),
    ])


def test_any_role_allows_authenticated_user():
    eng = _build_engine()
    assert eng.can_transition('draft', 'submitted', user=_FakeUser())


def test_role_keyword_checks_user_property():
    eng = _build_engine()
    manager = _FakeUser(can_manage_foia=True)
    noone = _FakeUser()
    assert eng.can_transition('submitted', 'approved', user=manager)
    assert not eng.can_transition('submitted', 'approved', user=noone)


def test_exact_role_string_checks_user_role():
    eng = _build_engine()
    admin = _FakeUser(role='system_admin')
    reviewer = _FakeUser(role='reviewer')
    assert eng.can_transition('approved', 'closed', user=admin)
    assert not eng.can_transition('approved', 'closed', user=reviewer)


def test_unknown_transition_raises_validation_error():
    eng = _build_engine()
    obj = type('O', (), {'status': 'draft', 'save': lambda self, *a, **k: None})()
    with pytest.raises(ValidationError):
        eng.execute(obj, 'closed', user=_FakeUser(), save=False)


def test_execute_without_role_raises_permission_denied():
    eng = _build_engine()
    obj = type('O', (), {'status': 'submitted', 'save': lambda self, *a, **k: None})()
    with pytest.raises(PermissionDenied):
        eng.execute(obj, 'approved', user=_FakeUser(role='applicant'), save=False)


def test_require_comment_enforced():
    eng = _build_engine()
    obj = type('O', (), {'status': 'submitted', 'save': lambda self, *a, **k: None})()
    manager = _FakeUser(can_manage_foia=True)
    with pytest.raises(ValidationError):
        eng.execute(obj, 'rejected', user=manager, save=False)
    # With a comment, the transition succeeds.
    eng.execute(obj, 'rejected', user=manager, comment='not enough evidence', save=False)
    assert obj.status == 'rejected'


def test_get_available_transitions_filters_by_role():
    eng = _build_engine()
    user = _FakeUser(can_manage_foia=True)
    available = eng.get_available_transitions('submitted', user=user)
    assert {t.to_status for t in available} == {'approved', 'rejected'}
    stranger = _FakeUser()
    assert eng.get_available_transitions('submitted', user=stranger) == []
