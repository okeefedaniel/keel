"""Render tests for the Wave 1 collaboration panel + its two new sub-includes
(attachment_list.html, quick_info.html).

Pins the public contract via Template().render(Context(...)) — no Django ORM
required. Each new component is tested against a small set of fake entities
that stand in for what real product subclasses would pass.

The orchestrator (collaboration_panel.html) is tested in two modes:
  - expanded (default) — all five sub-sections render in order
  - collapsed (Admiralty carve-out) — wrapped in <details> with summary

Sub-section opt-out: each sub-section's data kwarg can be omitted to skip
that section. Tests cover omitting collaborators, notes, attachments
individually, plus the all-five-omitted minimum panel (just claim_row +
workflow_transitions, both of which self-hide if their preconditions aren't
met).
"""
from datetime import datetime, timezone

from django.template import Context, Template
from django.template.loader import get_template


# --- attachment_list.html ---

class _FakeFile:
    def __init__(self, url='/media/foo.pdf'):
        self.url = url


class _FakeUser:
    def __init__(self, full_name='Alice Admin', username='alice', is_staff=False):
        self._full_name = full_name
        self.username = username
        self.is_staff = is_staff
        self.is_authenticated = True

    def get_full_name(self):
        return self._full_name


class _FakeAttachment:
    def __init__(self, filename='doc.pdf', size_bytes=2048,
                 visibility='external', source='upload',
                 manifest_packet_uuid='', uploaded_by=None,
                 uploaded_at=None):
        self.file = _FakeFile(url=f'/media/{filename}')
        self.filename = filename
        self.size_bytes = size_bytes
        self.visibility = visibility
        self.source = source
        self.manifest_packet_uuid = manifest_packet_uuid
        self.uploaded_by = uploaded_by
        self.uploaded_at = uploaded_at or datetime(2026, 5, 14, tzinfo=timezone.utc)


def _render_attachments(**ctx):
    return get_template('keel/components/attachment_list.html').render(ctx)


def test_attachment_list_renders_files_and_metadata():
    user = _FakeUser()
    html = _render_attachments(
        attachments=[
            _FakeAttachment(filename='proposal.pdf', size_bytes=10240,
                            uploaded_by=user),
        ],
        upload_action='/foo/upload/',
        request=type('R', (), {'user': user})(),
    )
    assert 'proposal.pdf' in html
    assert 'href="/media/proposal.pdf"' in html
    assert 'Alice Admin' in html
    assert 'action="/foo/upload/"' in html


def test_attachment_list_manifest_signed_badge():
    """Signed PDFs from Manifest get a distinguishing badge + green icon."""
    user = _FakeUser()
    html = _render_attachments(
        attachments=[
            _FakeAttachment(filename='grant_agreement.pdf',
                            source='manifest_signed',
                            manifest_packet_uuid='abc-123',
                            uploaded_by=user),
        ],
        request=type('R', (), {'user': user})(),
    )
    assert 'Signed via Manifest' in html
    assert 'bi-file-earmark-check' in html


def test_attachment_list_hides_internal_from_non_staff():
    """Defense in depth: per-row visibility filter hides 'internal' rows
    from non-staff users at render time, even if the view forgot to filter.
    """
    external_user = _FakeUser(is_staff=False)
    html = _render_attachments(
        attachments=[
            _FakeAttachment(filename='public.pdf', visibility='external'),
            _FakeAttachment(filename='staff_only.pdf', visibility='internal'),
        ],
        request=type('R', (), {'user': external_user})(),
    )
    assert 'public.pdf' in html
    assert 'staff_only.pdf' not in html


def test_attachment_list_shows_internal_to_staff():
    staff = _FakeUser(is_staff=True)
    html = _render_attachments(
        attachments=[
            _FakeAttachment(filename='public.pdf', visibility='external'),
            _FakeAttachment(filename='staff_only.pdf', visibility='internal'),
        ],
        request=type('R', (), {'user': staff})(),
    )
    assert 'public.pdf' in html
    assert 'staff_only.pdf' in html
    assert 'Internal' in html  # badge


def test_attachment_list_empty_state_with_no_upload_action():
    """No attachments + no upload URL → just the 'No attachments yet' message,
    no form.
    """
    html = _render_attachments(attachments=[], request=type('R', (), {'user': _FakeUser()})())
    assert 'No attachments yet.' in html
    assert '<form' not in html


def test_attachment_list_empty_state_with_upload_form():
    html = _render_attachments(
        attachments=[],
        upload_action='/foo/upload/',
        request=type('R', (), {'user': _FakeUser()})(),
    )
    assert 'No attachments yet.' in html
    assert 'action="/foo/upload/"' in html


# --- quick_info.html ---

def _render_quick_info(**ctx):
    return get_template('keel/components/quick_info.html').render(ctx)


def test_quick_info_renders_all_provided_rows():
    html = _render_quick_info(
        status_label='In Review',
        claimant=_FakeUser(full_name='Alice Admin'),
        principal=_FakeUser(full_name='Sen. Smith', username='smith'),
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    assert 'In Review' in html
    assert 'Alice Admin' in html
    assert 'Sen. Smith' in html
    assert 'Created' in html
    assert 'Updated' in html


def test_quick_info_skips_missing_rows():
    """Each row renders only when its data is provided."""
    html = _render_quick_info(status_label='Active')
    assert 'Active' in html
    assert 'Claimant' not in html
    assert 'Principal' not in html
    assert 'Created' not in html


def test_quick_info_renders_extra_fields():
    """Caller-supplied (label, value) tuples render as additional rows."""
    html = _render_quick_info(
        status_label='Approved',
        extra_fields=[
            ('FOIA #', 'FOIA-2026-042'),
            ('Days Remaining', '12'),
        ],
    )
    assert 'FOIA #' in html
    assert 'FOIA-2026-042' in html
    assert 'Days Remaining' in html


# --- collaboration_panel.html (orchestrator) ---

class _FakeAssignment:
    def __init__(self, user=None, assignment_type='claimed', status='assigned',
                 claimed_at=None):
        self.assigned_to = user
        self._assignment_type = assignment_type
        self._status = status
        self.claimed_at = claimed_at or datetime(2026, 5, 1, tzinfo=timezone.utc)

    def get_assignment_type_display(self):
        return self._assignment_type.replace('_', ' ').title()

    def get_status_display(self):
        return self._status.replace('_', ' ').title()


class _FakeCollaborator:
    def __init__(self, user=None, email='', name='', role='contributor',
                 is_active=True, invited_at=None):
        self.user = user
        self.email = email
        self.name = name
        self.role = role
        self.is_active = is_active
        self.invited_at = invited_at or datetime(2026, 5, 1, tzinfo=timezone.utc)
        self.pk = id(self)

    @property
    def is_external(self):
        return self.user is None

    @property
    def is_pending(self):
        return self.user is None or False


class _FakeNote:
    def __init__(self, author, content='Test note', is_internal=False,
                 created_at=None):
        self.author = author
        self.content = content
        self.is_internal = is_internal
        self.created_at = created_at or datetime(2026, 5, 10, tzinfo=timezone.utc)


class _FakeTransition:
    def __init__(self, to_status, label=''):
        self.to_status = to_status
        self.label = label


def _render_panel(**ctx):
    return get_template('keel/components/collaboration_panel.html').render(ctx)


def test_panel_renders_all_five_sections_when_data_present():
    user = _FakeUser()
    html = _render_panel(
        entity=object(),
        entity_label='invitation',
        active_assignment=_FakeAssignment(user=user),
        is_archived=False,
        collaborators=[_FakeCollaborator(user=user, role='lead')],
        notes=[_FakeNote(author=user)],
        attachments=[_FakeAttachment(uploaded_by=user)],
        available_transitions=[_FakeTransition('completed', 'Mark Complete')],
        claim_action='/foo/claim/',
        transition_action='/foo/transition/',
        note_form_action='/foo/notes/',
        attachment_upload_action='/foo/attach/',
        request=type('R', (), {'user': user})(),
    )
    # All five sub-sections render
    assert 'Collaborators' in html       # collaborator_list
    assert 'Comments' in html             # comment_section
    assert 'Workflow' in html             # workflow card chrome
    assert 'Mark Complete' in html        # workflow_transitions
    assert 'Attachments' in html          # attachment_list


def test_panel_hides_claim_row_when_already_claimed():
    user = _FakeUser()
    html = _render_panel(
        entity=object(),
        entity_label='invitation',
        active_assignment=_FakeAssignment(user=user),  # already claimed
        is_archived=False,
        collaborators=[],
        notes=[],
        attachments=[],
        available_transitions=[],
        claim_action='/foo/claim/',
        request=type('R', (), {'user': user})(),
    )
    assert 'This invitation has no lead' not in html  # claim banner suppressed


def test_panel_shows_claim_row_when_unclaimed():
    user = _FakeUser()
    html = _render_panel(
        entity=object(),
        entity_label='invitation',
        active_assignment=None,
        is_archived=False,
        collaborators=[],
        notes=[],
        attachments=[],
        available_transitions=[],
        claim_action='/foo/claim/',
        request=type('R', (), {'user': user})(),
    )
    assert 'This invitation has no lead' in html


def test_panel_omits_sub_section_when_data_kwarg_unset():
    """Pass no `collaborators` → collaborator section is skipped entirely."""
    user = _FakeUser()
    html = _render_panel(
        entity=object(),
        entity_label='invitation',
        active_assignment=None,
        is_archived=False,
        # collaborators NOT passed
        # notes NOT passed
        # attachments NOT passed
        available_transitions=[],
        claim_action='/foo/claim/',
        request=type('R', (), {'user': user})(),
    )
    assert 'Collaborators' not in html
    assert 'Comments' not in html
    assert 'Attachments' not in html
    # Claim banner still renders (data-less)
    assert 'This invitation has no lead' in html


def test_panel_collapsed_mode_wraps_in_details():
    """Admiralty carve-out: collapsed=True wraps the panel in <details>
    with a single-line summary showing collaborator + note counts.
    """
    user = _FakeUser()
    html = _render_panel(
        entity=object(),
        entity_label='request',
        active_assignment=_FakeAssignment(user=user),
        is_archived=False,
        collaborators=[_FakeCollaborator(user=user), _FakeCollaborator(user=user)],
        notes=[_FakeNote(author=user), _FakeNote(author=user, is_internal=True)],
        attachments=[_FakeAttachment(uploaded_by=user)],
        available_transitions=[],
        claim_action='/foo/claim/',
        transition_action='/foo/transition/',
        note_form_action='/foo/notes/',
        attachment_upload_action='/foo/attach/',
        collapsed=True,
        request=type('R', (), {'user': user})(),
    )
    assert '<details' in html
    assert '<summary' in html
    assert '2 members' in html
    assert '2 notes' in html
    assert '1 file' in html


def test_panel_collapsed_shows_unclaimed_when_no_assignment():
    user = _FakeUser()
    html = _render_panel(
        entity=object(),
        entity_label='request',
        active_assignment=None,
        is_archived=False,
        collaborators=[],
        notes=[],
        attachments=[],
        available_transitions=[],
        collapsed=True,
        request=type('R', (), {'user': user})(),
    )
    assert '<details' in html
    assert 'unclaimed' in html
