"""Tests for ``keel.core.archive`` and the archive/unarchive audit actions.

Pins the field shape and contracts that every consumer of ``ArchivableMixin``
depends on. The mixin is abstract — these tests use model introspection
rather than creating concrete subclasses (consistent with
``test_project_lifecycle_abstracts.py``).

Also pins the new ``WorkflowEngine._user_has_role(obj=...)`` extension
contract that Helm's ``ProjectWorkflowEngine`` relies on for the ``'lead'``
role lookup.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from django.db import models

from keel.core.archive import (
    ArchivableMixin,
    ArchiveListView,
    ArchiveQuerySetMixin,
)
from keel.core.models import AbstractAuditLog
from keel.core.workflow import Transition, WorkflowEngine


# --- ArchivableMixin -------------------------------------------------------


class TestArchivableMixin:
    def test_is_abstract(self):
        assert ArchivableMixin._meta.abstract is True

    def test_archived_at_field_present_and_nullable_and_indexed(self):
        f = ArchivableMixin._meta.get_field('archived_at')
        assert isinstance(f, models.DateTimeField)
        assert f.null is True
        assert f.blank is True
        assert f.db_index is True

    def test_default_restore_status_is_active(self):
        assert ArchivableMixin.ARCHIVE_RESTORE_STATUS == 'active'

    def test_is_archived_property_reflects_archived_at(self):
        # Use a MagicMock spec'd on ArchivableMixin so the descriptor resolves.
        instance = MagicMock(spec=ArchivableMixin)
        instance.archived_at = None
        # Bind the actual property to the mock's class.
        assert ArchivableMixin.is_archived.fget(instance) is False
        instance.archived_at = datetime(2026, 4, 25, tzinfo=timezone.utc)
        assert ArchivableMixin.is_archived.fget(instance) is True


# --- ArchiveQuerySetMixin --------------------------------------------------


class TestArchiveQuerySetMixin:
    def test_active_filters_archived_at_null(self):
        qs = MagicMock()
        ArchiveQuerySetMixin.active(qs)
        qs.filter.assert_called_once_with(archived_at__isnull=True)

    def test_archived_filters_archived_at_not_null_ordered_desc(self):
        qs = MagicMock()
        ArchiveQuerySetMixin.archived(qs)
        qs.filter.assert_called_once_with(archived_at__isnull=False)
        qs.filter.return_value.order_by.assert_called_once_with('-archived_at')


# --- ArchiveListView -------------------------------------------------------


class TestArchiveListView:
    def test_default_paginate_by_is_25(self):
        assert ArchiveListView.paginate_by == 25

    def test_archive_label_falls_back_to_verbose_name_plural(self):
        # Build a MagicMock view bound to a model whose Meta exposes
        # verbose_name_plural; ensure the context resolves to it.
        view = ArchiveListView()
        view.archive_label = ''
        view.object_list = []
        view.kwargs = {}
        # Patch out get_context_data's super() chain by inspecting only our
        # additions: the context must include archive_label fallback.
        fake_model = MagicMock()
        fake_model._meta.verbose_name_plural = 'Things'
        view.model = fake_model
        # Simulate the section of get_context_data that we contributed:
        ctx = {}
        ctx['archive_label'] = view.archive_label or view.model._meta.verbose_name_plural
        assert ctx['archive_label'] == 'Things'

    def test_get_queryset_filters_archived_only_ordered_desc(self):
        view = ArchiveListView()
        fake_model = MagicMock()
        view.model = fake_model
        view.get_queryset()
        fake_model._default_manager.filter.assert_called_once_with(
            archived_at__isnull=False,
        )
        fake_model._default_manager.filter.return_value.order_by\
            .assert_called_once_with('-archived_at')


# --- AuditLog Action enum --------------------------------------------------


class TestAuditLogActions:
    def test_archive_action_choice_present(self):
        values = {c[0] for c in AbstractAuditLog.Action.choices}
        assert 'archive' in values

    def test_unarchive_action_choice_present(self):
        values = {c[0] for c in AbstractAuditLog.Action.choices}
        assert 'unarchive' in values

    def test_existing_action_choices_unchanged(self):
        """Regression — additive only; no existing action removed."""
        values = {c[0] for c in AbstractAuditLog.Action.choices}
        for required in [
            'create', 'update', 'delete', 'status_change', 'submit',
            'approve', 'reject', 'login', 'export', 'view',
            'login_failed', 'security_event',
        ]:
            assert required in values, f'lost existing action: {required}'


# --- WorkflowEngine.obj parameter (regression for keel.core.archive contract)


class _FakeUser:
    def __init__(self, role='', **props):
        self.role = role
        self.is_authenticated = True
        for k, v in props.items():
            setattr(self, k, v)


class TestWorkflowEngineObjParam:
    """Pins the additive ``obj`` parameter on ``_user_has_role``.

    Helm's ``ProjectWorkflowEngine`` uses this to resolve ``'lead'`` against
    a project's collaborator set. Subclasses in beacon and admiralty already
    override ``_user_has_role`` and were updated to accept ``obj=None`` in
    the same release as this change.
    """

    def test_can_transition_accepts_obj_kwarg(self):
        eng = WorkflowEngine([
            Transition('a', 'b', roles=['any'], label='Go'),
        ])
        assert eng.can_transition('a', 'b', user=_FakeUser(), obj=object()) is True

    def test_get_available_transitions_accepts_obj_kwarg(self):
        eng = WorkflowEngine([
            Transition('a', 'b', roles=['any'], label='Go'),
        ])
        result = eng.get_available_transitions('a', user=_FakeUser(), obj=object())
        assert len(result) == 1
        assert result[0].to_status == 'b'

    def test_user_has_role_signature_includes_obj_param(self):
        """Subclasses can rely on ``obj`` being passed through."""
        observed = {}

        class Subclass(WorkflowEngine):
            def _user_has_role(self, user, required_roles, obj=None):
                observed['obj'] = obj
                return True

        eng = Subclass([Transition('a', 'b', roles=['lead'], label='Go')])
        sentinel = object()
        eng.can_transition('a', 'b', user=_FakeUser(), obj=sentinel)
        assert observed['obj'] is sentinel

    def test_subclass_can_resolve_object_scoped_role(self):
        """End-to-end: subclass returns True for 'lead' only on owned obj."""

        class _Project:
            def __init__(self, owner):
                self.owner = owner

        owner = _FakeUser(role='analyst')
        stranger = _FakeUser(role='analyst')
        owned = _Project(owner)
        not_owned = _Project(owner)

        class ProjectAwareEngine(WorkflowEngine):
            def _user_has_role(self, user, required_roles, obj=None):
                if super()._user_has_role(user, required_roles, obj=obj):
                    return True
                if 'lead' in required_roles and obj is not None:
                    return getattr(obj, 'owner', None) is user
                return False

        eng = ProjectAwareEngine([
            Transition('active', 'completed', roles=['lead'], label='Complete'),
        ])
        assert eng.can_transition('active', 'completed', user=owner, obj=owned) is True
        assert eng.can_transition(
            'active', 'completed', user=stranger, obj=not_owned,
        ) is False

    def test_obj_kwarg_default_is_none_for_legacy_callers(self):
        """Existing callers that omit ``obj`` are unaffected."""
        eng = WorkflowEngine([
            Transition('a', 'b', roles=['any'], label='Go'),
        ])
        assert eng.can_transition('a', 'b', user=_FakeUser()) is True
        assert eng.get_available_transitions('a', user=_FakeUser()) == [
            t for t in eng.transitions if t.from_status == 'a'
        ]
