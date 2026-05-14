"""Render tests for the two suite-shared collaboration components promoted
from Helm in Wave 0 of the collaboration-panel rollout.

Pins:
1. ``keel/components/claim_row.html`` renders the banner when unclaimed +
   not archived + claim_action present; renders empty otherwise.
2. ``keel/components/workflow_transitions.html`` renders the form when
   transitions are available + transition_action present; renders empty
   otherwise.
3. entity_label defaults to "record" so callers that forget the kwarg get
   a sensible fallback instead of an empty word.
4. claim_action is required — without it the form would post to an empty
   action attribute, which is a footgun.

These tests use ``Template.render(Context(...))`` rather than
``render_to_string`` so they exercise the raw template logic without
relying on context processors or the request stack.
"""
from django.template import Context, Template
from django.template.loader import get_template


# --- claim_row.html ---

def _render_claim_row(**ctx):
    tpl = get_template('keel/components/claim_row.html')
    return tpl.render(ctx)


def test_claim_row_renders_when_unclaimed_and_not_archived():
    html = _render_claim_row(
        active_assignment=None,
        is_archived=False,
        claim_action='/foo/claim/',
        entity_label='project',
    )
    assert 'This project has no lead.' in html
    assert 'action="/foo/claim/"' in html
    assert 'Claim project' in html


def test_claim_row_uses_record_fallback_when_label_missing():
    html = _render_claim_row(
        active_assignment=None,
        is_archived=False,
        claim_action='/foo/claim/',
        # entity_label NOT passed
    )
    assert 'This record has no lead.' in html
    assert 'Claim record' in html


def test_claim_row_renders_empty_when_already_claimed():
    """An active assignment hides the banner — caller has a Lead already."""
    html = _render_claim_row(
        active_assignment=object(),  # truthy
        is_archived=False,
        claim_action='/foo/claim/',
        entity_label='project',
    )
    assert html.strip() == ''


def test_claim_row_renders_empty_when_archived():
    """Archived records can't be claimed — terminal state."""
    html = _render_claim_row(
        active_assignment=None,
        is_archived=True,
        claim_action='/foo/claim/',
        entity_label='project',
    )
    assert html.strip() == ''


def test_claim_row_renders_empty_without_claim_action():
    """No claim URL → no banner. Prevents accidental form-action="" footgun."""
    html = _render_claim_row(
        active_assignment=None,
        is_archived=False,
        # claim_action NOT passed
        entity_label='project',
    )
    assert html.strip() == ''


# --- workflow_transitions.html ---

class _FakeTransition:
    def __init__(self, to_status, label=''):
        self.to_status = to_status
        self.label = label


def _render_transitions(**ctx):
    tpl = get_template('keel/components/workflow_transitions.html')
    return tpl.render(ctx)


def test_workflow_transitions_renders_when_available_and_action_present():
    html = _render_transitions(
        available_transitions=[
            _FakeTransition('approved', 'Approve'),
            _FakeTransition('rejected', 'Reject'),
        ],
        transition_action='/foo/transition/',
    )
    assert 'action="/foo/transition/"' in html
    assert '<option value="approved">Approve</option>' in html
    assert '<option value="rejected">Reject</option>' in html
    assert 'name="comment"' in html


def test_workflow_transitions_falls_back_to_to_status_when_label_missing():
    """Transitions without a label render the to_status as the option text."""
    html = _render_transitions(
        available_transitions=[_FakeTransition('approved')],
        transition_action='/foo/transition/',
    )
    assert '<option value="approved">approved</option>' in html


def test_workflow_transitions_renders_empty_when_no_transitions():
    """Terminal state — no available transitions → no form. Mixin returns
    [] for archived/closed records.
    """
    html = _render_transitions(
        available_transitions=[],
        transition_action='/foo/transition/',
    )
    assert html.strip() == ''


def test_workflow_transitions_renders_empty_without_action():
    """No transition URL → no form, even if transitions are available.
    Prevents form-action="" footgun.
    """
    html = _render_transitions(
        available_transitions=[_FakeTransition('approved', 'Approve')],
        # transition_action NOT passed
    )
    assert html.strip() == ''
