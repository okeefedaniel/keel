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

    # Map of role keyword -> user property to check.
    # Products define these properties on their User model; products that
    # don't have a property are unaffected (getattr returns False).
    ROLE_PROPERTY_MAP = {
        # Cross-product
        'agency_staff': 'is_agency_staff',
        # Beacon (CRM / FOIA)
        'foia_staff': 'is_foia_staff',
        'foia_manager': 'can_manage_foia',
        'company_manager': 'can_manage_companies',
        'company_moderator': 'can_moderate_companies',
        # Harbor (grants)
        'grant_manager': 'can_manage_grants',
        'reviewer': 'is_reviewer',
        'federal_coordinator': 'is_federal_coordinator',
        # Purser (financial)
        'purser_reviewer': 'is_purser_reviewer',
    }

    def __init__(self, transitions: list[Transition] | None = None,
                 history_model=None, history_fk_field=None):
        self.transitions = transitions or []
        self._history_model = history_model      # dotted path or model class
        self._history_fk_field = history_fk_field  # FK field name on history model
        self._index: dict[str, list[Transition]] = {}
        self._rebuild_index()

    def get_available_transitions(self, current_status: str, user=None, obj=None):
        candidates = self._index.get(current_status, [])
        if user is None:
            return candidates
        return [t for t in candidates if self._user_has_role(user, t.roles, obj=obj)]

    def can_transition(self, current_status: str, target_status: str, user=None, obj=None) -> bool:
        for t in self._index.get(current_status, []):
            if t.to_status == target_status:
                if user is None or self._user_has_role(user, t.roles, obj=obj):
                    return True
        return False

    def execute(self, obj, target_status: str, user=None, comment: str = '', save=True):
        current = obj.status
        transition = self._find_transition(current, target_status)

        if transition is None:
            raise ValidationError(
                f"Transition from '{current}' to '{target_status}' is not allowed."
            )

        if user is not None and not self._user_has_role(user, transition.roles, obj=obj):
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

        # Auto-create status history record if configured
        self._record_history(obj, old_status, target_status, user, comment)

        # Emit a Track B `workflow.transitioned` activity row so every
        # WorkflowEngine-based product gets status-change visibility in the
        # activity panel for free. Best-effort: never blocks the transition
        # if keel.activity isn't installed or record_activity raises.
        self._record_activity(obj, old_status, target_status, user, comment, transition)

        if transition.on_complete:
            transition.on_complete(obj, user, comment)

        return transition

    def get_status_graph(self) -> dict[str, list[str]]:
        graph = {}
        for t in self.transitions:
            graph.setdefault(t.from_status, []).append(t.to_status)
        return graph

    def _resolve_history_model(self):
        """Lazily resolve the history model from a dotted path string."""
        if self._history_model is None:
            return None
        if isinstance(self._history_model, str):
            from django.apps import apps
            try:
                self._history_model = apps.get_model(self._history_model)
            except LookupError:
                logger.warning('History model %s not found', self._history_model)
                self._history_model = None
        return self._history_model

    def _record_history(self, obj, old_status, new_status, user, comment):
        """Create a status history record if a history model is configured."""
        model = self._resolve_history_model()
        if model is None or not self._history_fk_field:
            return
        try:
            model.objects.create(
                **{self._history_fk_field: obj},
                old_status=old_status,
                new_status=new_status,
                changed_by=user,
                comment=comment,
            )
        except Exception:
            logger.exception('Failed to create status history record')

    def _record_activity(self, obj, old_status, new_status, user, comment, transition):
        """Emit a `workflow.transitioned` activity row for the transition.

        Best-effort: never blocks the transition. No-ops cleanly when
        keel.activity isn't configured (KEEL_ACTIVITY_MODEL unset) or when
        record_activity itself raises.

        The source_label uses the transition's human label when available
        (e.g. "Submit", "Approve"), falling back to "transitioned to <state>".
        Metadata carries from_status / to_status / comment for downstream
        consumers (Helm aggregator, notification fan-out, etc).
        """
        from django.conf import settings
        if not getattr(settings, 'KEEL_ACTIVITY_MODEL', ''):
            return
        try:
            from keel.activity.services import record_activity
        except ImportError:
            return
        try:
            label = transition.label.strip() if transition.label else ''
            if label:
                # Lowercase first letter so it reads naturally after the actor
                # name in the activity panel: "Demo Admin marked approved" not
                # "Demo Admin Marked Approved".
                source_label = label[0].lower() + label[1:] if len(label) > 1 else label.lower()
            else:
                source_label = f'transitioned to {new_status}'
            record_activity(
                actor=user,
                verb='workflow.transitioned',
                target=obj,
                audit_action='status_change',
                visibility='collaborators',
                source_label=source_label,
                metadata={
                    'from_status': old_status,
                    'to_status': new_status,
                    'comment': comment or '',
                    'transition_label': transition.label or '',
                },
            )
        except Exception:
            logger.exception(
                'workflow.transitioned activity emission failed for '
                '%s %s -> %s (non-fatal)',
                obj.__class__.__name__, old_status, new_status,
            )

    def _rebuild_index(self):
        self._index = {}
        for t in self.transitions:
            self._index.setdefault(t.from_status, []).append(t)

    def _find_transition(self, from_status: str, to_status: str) -> Transition | None:
        for t in self._index.get(from_status, []):
            if t.to_status == to_status:
                return t
        return None

    def _user_has_role(self, user, required_roles: list[str], obj=None) -> bool:
        """Check whether ``user`` may perform a transition with ``required_roles``.

        ``obj`` is the model instance the transition is being attempted on.
        It is ignored by the base implementation; subclasses can use it to
        resolve object-scoped roles (e.g. ``'lead'`` against a project's
        collaborator set). See Helm's ``ProjectWorkflowEngine`` for a
        reference implementation.
        """
        if not required_roles or 'any' in required_roles:
            return True

        if getattr(user, 'is_superuser', False):
            return True

        role = getattr(user, 'role', '')
        # Admin-tier roles satisfy any role gate. ``system_admin`` is the
        # IT/platform admin (DockLabs operator); ``agency_admin`` is the
        # customer-side admin who runs their own org. Both are "above"
        # the operator-tier roles enumerated on each Transition, so they
        # bypass per-transition role lists the same way superusers do.
        if role in ('system_admin', 'agency_admin'):
            return True

        for r in required_roles:
            # Check role keyword -> property mapping
            prop = self.ROLE_PROPERTY_MAP.get(r)
            if prop and getattr(user, prop, False):
                return True
            # Exact role match
            if r == role:
                return True

        return False
