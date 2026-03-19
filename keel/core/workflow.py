"""
Configurable workflow engine for status transitions.

Provides a declarative way to define valid status transitions for any model
with a ``status`` field. Each product defines its own transitions; the engine
is shared.

Usage:
    from keel.core.workflow import Transition, WorkflowEngine

    MY_WORKFLOW = WorkflowEngine([
        Transition('draft', 'submitted', roles=['any'], label='Submit'),
        Transition('submitted', 'approved', roles=['manager'], label='Approve'),
    ])

    # Check if a user can transition
    if MY_WORKFLOW.can_transition(obj.status, 'approved', user):
        MY_WORKFLOW.execute(obj, 'approved', user=user)
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.core.exceptions import PermissionDenied, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class Transition:
    """A single allowed status transition."""

    from_status: str
    to_status: str
    roles: list = field(default_factory=list)
    label: str = ''
    description: str = ''
    require_comment: bool = False
    validators: list = field(default_factory=list)
    on_complete: Optional[Callable] = None

    def __str__(self):
        return f"{self.from_status} -> {self.to_status}"


class WorkflowEngine:
    """Manages valid status transitions for a model.

    The engine is role-aware: it checks user properties to determine
    whether a transition is allowed. Role keywords map to user properties:

    - 'any': any authenticated user
    - 'agency_staff': user.is_agency_staff
    - 'foia_staff': user.is_foia_staff
    - 'foia_manager': user.can_manage_foia
    - 'company_manager': user.can_manage_companies
    - 'company_moderator': user.can_moderate_companies

    Exact role matches (e.g., 'system_admin') check user.role directly.
    Products can add custom role keywords by subclassing and overriding
    ``_user_has_role``.
    """

    # Map of role keyword -> user property to check
    ROLE_PROPERTY_MAP = {
        'agency_staff': 'is_agency_staff',
        'foia_staff': 'is_foia_staff',
        'foia_manager': 'can_manage_foia',
        'company_manager': 'can_manage_companies',
        'company_moderator': 'can_moderate_companies',
    }

    def __init__(self, transitions: list[Transition] | None = None):
        self.transitions = transitions or []
        self._index: dict[str, list[Transition]] = {}
        self._rebuild_index()

    def get_available_transitions(self, current_status: str, user=None):
        candidates = self._index.get(current_status, [])
        if user is None:
            return candidates
        return [t for t in candidates if self._user_has_role(user, t.roles)]

    def can_transition(self, current_status: str, target_status: str, user=None) -> bool:
        for t in self._index.get(current_status, []):
            if t.to_status == target_status:
                if user is None or self._user_has_role(user, t.roles):
                    return True
        return False

    def execute(self, obj, target_status: str, user=None, comment: str = '', save=True):
        current = obj.status
        transition = self._find_transition(current, target_status)

        if transition is None:
            raise ValidationError(
                f"Transition from '{current}' to '{target_status}' is not allowed."
            )

        if user is not None and not self._user_has_role(user, transition.roles):
            raise PermissionDenied(
                f"User role '{getattr(user, 'role', 'unknown')}' cannot perform "
                f"transition '{transition}'."
            )

        if transition.require_comment and not comment.strip():
            raise ValidationError(
                f"A comment is required for this transition ({transition})."
            )

        for validator in transition.validators:
            validator(obj, user, comment)

        old_status = obj.status
        obj.status = target_status

        if save:
            obj.save(update_fields=['status', 'updated_at'])

        logger.info(
            "Workflow transition: %s %s -> %s (user=%s)",
            obj.__class__.__name__, old_status, target_status, user,
        )

        if transition.on_complete:
            transition.on_complete(obj, user, comment)

        return transition

    def get_status_graph(self) -> dict[str, list[str]]:
        graph = {}
        for t in self.transitions:
            graph.setdefault(t.from_status, []).append(t.to_status)
        return graph

    def _rebuild_index(self):
        self._index = {}
        for t in self.transitions:
            self._index.setdefault(t.from_status, []).append(t)

    def _find_transition(self, from_status: str, to_status: str) -> Transition | None:
        for t in self._index.get(from_status, []):
            if t.to_status == to_status:
                return t
        return None

    @classmethod
    def _user_has_role(cls, user, required_roles: list[str]) -> bool:
        if not required_roles or 'any' in required_roles:
            return True

        role = getattr(user, 'role', '')

        for r in required_roles:
            # Check role keyword -> property mapping
            prop = cls.ROLE_PROPERTY_MAP.get(r)
            if prop and getattr(user, prop, False):
                return True
            # Exact role match
            if r == role:
                return True

        return False
