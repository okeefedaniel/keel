"""Promotion registry — maps audit rows to activity verbs (Track A).

Per the spike findings (see ``MIGRATION-NOTES.md``), audit rows are keyed by
``(entity_type, action)`` where ``entity_type`` is the registered display name from
``keel.core.audit_signals.register_audited_model()`` (e.g. ``'Project Collaborator'``) and
``action`` is the AuditLog action enum value (``'create'``, ``'update'``, ``'delete'``,
``'status_change'``, ...).

Track A is for simple "audit row IS the activity event" cases (creates, deletes). Domain-
rich verbs that need from/to status or other structured metadata use Track B (explicit
``record_activity()`` calls in product service code).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class PromotionRule:
    """A single rule that promotes audit rows matching ``(entity_type, action)`` to an
    activity row of verb ``verb``.

    Visibility may be a static string OR a callable ``(audit) -> str`` that resolves the
    visibility tier per audit row. The callable form is required for Beacon's zone-aware
    verbs where the audited row's zone field determines whether the activity is
    collaborators-tier or stub-tier visibility.

    target_fn / action_fn / deep_link_fn / source_label_fn / metadata_fn are all callables
    that receive the audit row and return the corresponding piece of the activity row.
    The eng plan wires these as lambdas; the dataclass accepts any callable.
    """
    entity_type: str
    action: str
    verb: str
    visibility: Union[str, Callable[['AuditLog'], str]] = 'collaborators'
    target_fn: Optional[Callable] = None
    action_fn: Optional[Callable] = None
    deep_link_fn: Optional[Callable] = None
    source_label_fn: Optional[Callable] = None
    metadata_fn: Optional[Callable] = None

    def resolve_visibility(self, audit) -> str:
        """Resolve visibility for this audit row. Callable form is invoked per row."""
        if callable(self.visibility):
            return self.visibility(audit)
        return self.visibility

    def build_activity_kwargs(self, audit) -> Optional[dict]:
        """Build the kwargs for ``Activity.objects.create()``. Returns None to skip."""
        from django.conf import settings

        target = self.target_fn(audit) if self.target_fn else None
        if target is None and self.action != 'system':
            return None  # No target → skip. System events use record_activity() directly.

        action_obj = self.action_fn(audit) if self.action_fn else None
        deep_link = ''
        if hasattr(audit, 'deep_link_snapshot') and audit.deep_link_snapshot:
            deep_link = audit.deep_link_snapshot
        elif self.deep_link_fn:
            try:
                deep_link = self.deep_link_fn(audit) or ''
            except Exception:
                # Stale URL pattern, deleted target, etc. Promotion never blocks audit.
                logger.debug('deep_link_fn failed for audit %s', audit.pk, exc_info=True)
                deep_link = ''

        source_label = ''
        if self.source_label_fn:
            try:
                source_label = self.source_label_fn(audit) or ''
            except Exception:
                logger.debug('source_label_fn failed for audit %s', audit.pk, exc_info=True)
                source_label = f'{audit.user} {self.verb}'

        metadata = {}
        if self.metadata_fn:
            try:
                metadata = self.metadata_fn(audit) or {}
            except Exception:
                logger.debug('metadata_fn failed for audit %s', audit.pk, exc_info=True)

        return {
            'actor': audit.user,
            'verb': self.verb,
            'target': target,
            'action': action_obj,
            'visibility': self.resolve_visibility(audit),
            'source_product': settings.KEEL_PRODUCT_CODE,
            'deep_link': deep_link,
            'source_label': source_label,
            'metadata': metadata,
        }


class PromotionRegistry:
    """Module-level registry of promotion rules. Keyed on ``(entity_type, action)``.

    Rules are registered at app-ready time via ``product_promotions.register_all_promotions()``
    which calls per-product ``_register_<product>_promotions()`` functions. Standalone
    deploys skip peers' registrations because their apps aren't installed.

    Last-write-wins on key collisions, with a logged warning. ``unregister()`` removes
    a rule explicitly.
    """
    _rules: dict[tuple[str, str], PromotionRule] = {}

    @classmethod
    def register(cls, rule: PromotionRule, override: bool = False) -> None:
        key = (rule.entity_type, rule.action)
        if key in cls._rules and not override:
            existing = cls._rules[key]
            logger.warning(
                'Promotion rule for %s already registered with verb=%s; new rule with '
                'verb=%s ignored. Pass override=True to replace.',
                key, existing.verb, rule.verb,
            )
            return
        cls._rules[key] = rule

    @classmethod
    def unregister(cls, entity_type: str, action: str) -> None:
        cls._rules.pop((entity_type, action), None)

    @classmethod
    def lookup(cls, entity_type: str, action: str) -> Optional[PromotionRule]:
        return cls._rules.get((entity_type, action))

    @classmethod
    def all_rules(cls) -> list[PromotionRule]:
        return list(cls._rules.values())

    @classmethod
    def reset(cls) -> None:
        """Clear the registry. ONLY for test isolation; never call in production code."""
        cls._rules.clear()


def activity_promotion(
    entity_type: str,
    action: str,
    verb: str,
    visibility: Union[str, Callable] = 'collaborators',
    deep_link_fn: Optional[Callable] = None,
    source_label_fn: Optional[Callable] = None,
    target_fn: Optional[Callable] = None,
    action_fn: Optional[Callable] = None,
    override: bool = False,
):
    """Decorator. The decorated function is the ``metadata_fn`` for the rule.

    Other rule fields are decorator kwargs. Returning None from the decorated function
    is a soft skip (audit row recorded but no activity emitted).

    Usage:

        @activity_promotion(
            entity_type='Project Collaborator',
            action='create',
            verb='collab.added',
            target_fn=lambda audit: ProjectCollaborator.objects.get(pk=audit.entity_id).project,
            source_label_fn=lambda audit: f'added a collaborator',
        )
        def metadata_for_collab_added(audit):
            collab = ProjectCollaborator.objects.get(pk=audit.entity_id)
            return {'role': collab.role}
    """
    def wrapper(metadata_fn):
        rule = PromotionRule(
            entity_type=entity_type,
            action=action,
            verb=verb,
            visibility=visibility,
            target_fn=target_fn,
            action_fn=action_fn,
            deep_link_fn=deep_link_fn,
            source_label_fn=source_label_fn,
            metadata_fn=metadata_fn,
        )
        PromotionRegistry.register(rule, override=override)
        return metadata_fn
    return wrapper
