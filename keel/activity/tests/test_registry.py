"""Tests for keel.activity.registry — the Track A promotion registry.

Covers:
    - register / unregister / lookup roundtrips
    - last-write-wins on collision (with override flag)
    - PromotionRule.resolve_visibility for both string and callable forms
    - PromotionRule.build_activity_kwargs returns None when target_fn returns None
"""
import pytest

from keel.activity.registry import (
    PromotionRegistry,
    PromotionRule,
    activity_promotion,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Each test starts with a clean registry; cleanup at teardown."""
    PromotionRegistry.reset()
    yield
    PromotionRegistry.reset()


def test_register_and_lookup():
    rule = PromotionRule(
        entity_type='Project Collaborator',
        action='create',
        verb='collab.added',
    )
    PromotionRegistry.register(rule)

    found = PromotionRegistry.lookup('Project Collaborator', 'create')
    assert found is rule

    not_found = PromotionRegistry.lookup('Project Collaborator', 'delete')
    assert not_found is None


def test_register_collision_keeps_first_unless_override(caplog):
    rule_a = PromotionRule(entity_type='X', action='create', verb='verb.a')
    rule_b = PromotionRule(entity_type='X', action='create', verb='verb.b')

    PromotionRegistry.register(rule_a)
    with caplog.at_level('WARNING'):
        PromotionRegistry.register(rule_b)

    # First wins
    assert PromotionRegistry.lookup('X', 'create') is rule_a
    assert any('already registered' in r.message for r in caplog.records)

    # Override replaces
    PromotionRegistry.register(rule_b, override=True)
    assert PromotionRegistry.lookup('X', 'create') is rule_b


def test_unregister():
    rule = PromotionRule(entity_type='Y', action='delete', verb='lifecycle.deleted')
    PromotionRegistry.register(rule)
    assert PromotionRegistry.lookup('Y', 'delete') is rule

    PromotionRegistry.unregister('Y', 'delete')
    assert PromotionRegistry.lookup('Y', 'delete') is None

    # unregister of unknown key is a no-op (does not raise)
    PromotionRegistry.unregister('not-there', 'create')


def test_resolve_visibility_static_string():
    rule = PromotionRule(entity_type='X', action='create', verb='verb.a',
                         visibility='staff')
    assert rule.resolve_visibility(audit=None) == 'staff'


def test_resolve_visibility_callable():
    """Beacon's zone-aware case: visibility depends on the audited row."""
    def visibility_fn(audit):
        # Simulate Beacon's logic — return stub when zone is restricted.
        return 'stub' if audit.zone != 'shared' else 'collaborators'

    rule = PromotionRule(
        entity_type='Interaction', action='create', verb='interaction.logged',
        visibility=visibility_fn,
    )

    class FakeAudit:
        def __init__(self, zone):
            self.zone = zone

    assert rule.resolve_visibility(FakeAudit('shared')) == 'collaborators'
    assert rule.resolve_visibility(FakeAudit('agency_internal')) == 'stub'
    assert rule.resolve_visibility(FakeAudit('quasi_private')) == 'stub'


def test_build_activity_kwargs_returns_none_when_target_fn_yields_none():
    """Target_fn returning None means 'skip this row' — graceful degradation when the
    target was deleted between audit-write and promotion."""
    rule = PromotionRule(
        entity_type='X', action='create', verb='verb.a',
        target_fn=lambda audit: None,
    )

    class FakeAudit:
        pk = 1

    assert rule.build_activity_kwargs(FakeAudit()) is None


def test_decorator_registers_rule():
    @activity_promotion(
        entity_type='Z', action='create', verb='verb.z',
        target_fn=lambda audit: 'fake-target',
    )
    def metadata_for_z(audit):
        return {'zone': 'whatever'}

    found = PromotionRegistry.lookup('Z', 'create')
    assert found is not None
    assert found.verb == 'verb.z'
    assert found.metadata_fn is metadata_for_z
