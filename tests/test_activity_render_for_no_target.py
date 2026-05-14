"""Regression test: ``AbstractActivity.render_for`` does NOT dereference target.

Before keel 0.40.3, ``render_for`` returned ``{'target': self.target, ...}`` —
a GenericForeignKey lookup per row. The bundled ``_panel.html`` partial never
read ``target``; the dereference was dead weight that turned a 15-row activity
panel render into 15 extra ContentType + model lookups (N+1).

This test pins the contract: the default returned dict does NOT include
``target``. Subclasses that need ``target`` for their own templates must
override ``render_for`` AND prefetch ``target_ct`` (or accept the cost).
"""
from unittest.mock import MagicMock

from keel.activity.models import AbstractActivity


def _fake_row(visibility='collaborators'):
    """A MagicMock that pretends to be an AbstractActivity row.

    We don't instantiate the abstract model (Django would complain), and we
    don't need a concrete subclass for this contract test. We just stand up
    the attributes ``render_for`` reads from ``self`` and call the unbound
    method directly.
    """
    row = MagicMock(spec=AbstractActivity)
    row.actor = MagicMock()
    row.actor.__str__ = lambda self: 'alice'
    row.verb = 'workflow.transitioned'
    row.deep_link = '/foo/bar/'
    row.source_label = 'Alice moved Project A to approved'
    row.created_at = '2026-05-14T13:00:00Z'
    row.metadata = {'from': 'review', 'to': 'approved'}
    row.visibility = visibility
    # `target` IS attached so a regression that adds it back would silently
    # populate from the mock instead of failing — we want the contract to be
    # "key not present" not "value is None".
    row.target = MagicMock(name='target_object')
    return row


def test_render_for_does_not_include_target_key_default_tier():
    """Default-tier (collaborators/agency/staff/public) rows MUST NOT
    return 'target' in the rendered dict.
    """
    row = _fake_row(visibility='collaborators')
    result = AbstractActivity.render_for(row, user=None)
    assert 'target' not in result, (
        "render_for returned 'target' — this re-introduces the per-row GFK "
        "N+1 the 0.40.2 work eliminated. If you need target in your "
        "rendering, override render_for in your concrete subclass AND prefetch."
    )
    # Pin the keys we DO expect so the contract is explicit.
    assert set(result.keys()) == {
        'actor_name', 'verb', 'deep_link', 'source_label',
        'created_at', 'metadata', 'is_stub',
    }
    assert result['is_stub'] is False


def test_render_for_stub_tier_unchanged():
    """Stub-tier rows (Beacon cross-zone) keep their narrow shape — actor +
    verb + created_at + is_stub. No regression there.
    """
    row = _fake_row(visibility='stub')
    result = AbstractActivity.render_for(row, user=None)
    assert 'target' not in result
    assert set(result.keys()) == {'actor_name', 'verb', 'created_at', 'is_stub'}
    assert result['is_stub'] is True


def test_render_for_actor_none_resolves_to_system():
    """System-emitted activity (no actor) renders as 'system'."""
    row = _fake_row()
    row.actor = None
    result = AbstractActivity.render_for(row, user=None)
    assert result['actor_name'] == 'system'
