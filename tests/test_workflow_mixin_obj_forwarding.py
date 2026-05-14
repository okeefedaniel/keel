"""Regression test: ``WorkflowModelMixin`` MUST forward ``obj=self`` to engine.

Before keel 0.40.2, ``WorkflowModelMixin.get_available_transitions`` and
``can_transition`` called the engine without ``obj=self``, silently breaking
object-scoped role checks in subclasses (e.g. Helm's ``ProjectWorkflowEngine``
resolving the ``'lead'`` role per-project against ``ProjectCollaborator``
rows). The engine's documented contract in ``keel/CLAUDE.md`` under
"Object-scoped roles" requires forwarding; the mixin violated it. Result:
workflow buttons rendered to the wrong users — a security boundary defect.

This test pins the contract via a fake ``ObjectScopedEngine`` subclass that
returns True iff ``obj`` itself satisfies the role. If the mixin forwards
``obj`` correctly, the same user gets different transition sets on two
different model instances (the user is "lead" on one, not the other).
If the mixin drops ``obj``, both instances see the same fallback behaviour.
"""
import pytest

from keel.core.models import WorkflowModelMixin
from keel.core.workflow import Transition, WorkflowEngine


class _FakeUser:
    def __init__(self, name):
        self.name = name
        self.is_authenticated = True
        self.role = ''  # ROLE_PROPERTY_MAP fallback


class ObjectScopedEngine(WorkflowEngine):
    """Test engine: 'lead' role resolves against ``obj.lead`` identity."""

    def _user_has_role(self, user, required_roles, obj=None):
        if 'lead' in required_roles:
            # If obj wasn't forwarded, this comparison is meaningless — fall
            # through to the base implementation, which doesn't know how to
            # resolve 'lead'.
            if obj is None:
                return super()._user_has_role(user, required_roles, obj=obj)
            return getattr(obj, 'lead', None) is user
        return super()._user_has_role(user, required_roles, obj=obj)


PROJECT_WORKFLOW = ObjectScopedEngine([
    Transition('active', 'closed', roles=['lead'], label='Close'),
])


class _Project(WorkflowModelMixin):
    """Plain-old-Python WorkflowModelMixin consumer — no Django ORM."""
    WORKFLOW = PROJECT_WORKFLOW

    def __init__(self, lead):
        self.status = 'active'
        self.lead = lead


def test_get_available_transitions_forwards_obj():
    """A user who is lead on one project but not another must see different
    available transitions on each project — only possible if obj=self is
    forwarded from the mixin to the engine.
    """
    alice = _FakeUser('alice')
    bob = _FakeUser('bob')
    alice_project = _Project(lead=alice)
    bob_project = _Project(lead=bob)

    # Alice sees the 'Close' transition only on her own project.
    assert [t.to_status for t in alice_project.get_available_transitions(alice)] == ['closed']
    assert [t.to_status for t in bob_project.get_available_transitions(alice)] == []

    # Bob sees the symmetric thing.
    assert [t.to_status for t in bob_project.get_available_transitions(bob)] == ['closed']
    assert [t.to_status for t in alice_project.get_available_transitions(bob)] == []


def test_can_transition_forwards_obj():
    """can_transition() honours the per-record role check."""
    alice = _FakeUser('alice')
    bob = _FakeUser('bob')
    alice_project = _Project(lead=alice)
    bob_project = _Project(lead=bob)

    # Alice can close her own project, not bob's.
    assert alice_project.can_transition('closed', user=alice) is True
    assert bob_project.can_transition('closed', user=alice) is False

    # Bob, symmetric.
    assert bob_project.can_transition('closed', user=bob) is True
    assert alice_project.can_transition('closed', user=bob) is False


def test_transition_forwards_obj():
    """transition() already worked pre-fix because execute() takes obj
    positionally, but pin it so a future refactor doesn't break it.
    """
    alice = _FakeUser('alice')
    project = _Project(lead=alice)
    # Stub .save() so execute(save=True) doesn't try ORM persistence.
    project.save = lambda *a, **kw: None
    project.transition('closed', user=alice)
    assert project.status == 'closed'

    # A non-lead user cannot drive the transition.
    bob = _FakeUser('bob')
    other = _Project(lead=alice)
    other.save = lambda *a, **kw: None
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        other.transition('closed', user=bob)
