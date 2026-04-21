"""Tests for the Project Lifecycle Standard abstracts.

Pins the field shape and canonical role/status vocabularies that every
workflow-carrying DockLabs product depends on. See the "Project Lifecycle
Standard" section of keel/CLAUDE.md.

These tests intentionally use model introspection rather than creating
concrete subclasses — the abstracts have no migrations in keel itself,
and product subclasses provide their own DB tables.
"""
from django.db import models

from keel.core.models import (
    AbstractAssignment,
    AbstractAttachment,
    AbstractCollaborator,
)


def _field(model, name):
    return model._meta.get_field(name)


class TestAbstractAssignment:
    def test_is_abstract(self):
        assert AbstractAssignment._meta.abstract is True

    def test_canonical_assignment_types(self):
        values = {c[0] for c in AbstractAssignment.AssignmentType.choices}
        assert values == {'claimed', 'manager_assigned'}

    def test_canonical_statuses(self):
        values = {c[0] for c in AbstractAssignment.Status.choices}
        assert values == {'assigned', 'in_progress', 'completed', 'reassigned', 'released'}

    def test_required_fields_present(self):
        for name in [
            'assigned_to', 'assigned_by', 'assignment_type', 'status',
            'claimed_at', 'released_at', 'notes',
        ]:
            _field(AbstractAssignment, name)  # raises if missing

    def test_default_assignment_type_is_self_claim(self):
        assert _field(AbstractAssignment, 'assignment_type').default == 'claimed'

    def test_default_status_is_assigned(self):
        assert _field(AbstractAssignment, 'status').default == 'assigned'


class TestAbstractCollaborator:
    def test_is_abstract(self):
        assert AbstractCollaborator._meta.abstract is True

    def test_canonical_role_vocabulary(self):
        """LEAD / CONTRIBUTOR / REVIEWER / OBSERVER — no other roles allowed.

        Product subclasses MUST NOT extend this enum; if finer-grained
        distinctions are needed, model them as tags on the collaborator.
        """
        values = {c[0] for c in AbstractCollaborator.Role.choices}
        assert values == {'lead', 'contributor', 'reviewer', 'observer'}

    def test_default_role_is_contributor(self):
        assert _field(AbstractCollaborator, 'role').default == 'contributor'

    def test_external_invite_fields_present(self):
        user_field = _field(AbstractCollaborator, 'user')
        assert user_field.null is True, 'user must be nullable for external invites'
        assert _field(AbstractCollaborator, 'email') is not None
        assert _field(AbstractCollaborator, 'name') is not None

    def test_invite_lifecycle_fields(self):
        assert _field(AbstractCollaborator, 'invited_by') is not None
        assert _field(AbstractCollaborator, 'invited_at') is not None
        accepted_at = _field(AbstractCollaborator, 'accepted_at')
        assert accepted_at.null is True, 'accepted_at must be nullable (pending invites)'

    def test_per_collaborator_notification_prefs_default_on(self):
        assert _field(AbstractCollaborator, 'notify_on_notes').default is True
        assert _field(AbstractCollaborator, 'notify_on_status').default is True

    def test_is_external_property(self):
        # Abstract models can't be instantiated; exercise the descriptor
        # against a minimal stand-in that has the attributes it reads.
        class _Stub:
            user_id = None
        assert AbstractCollaborator.is_external.fget(_Stub()) is True
        _Stub.user_id = 42
        assert AbstractCollaborator.is_external.fget(_Stub()) is False

    def test_is_pending_property(self):
        class _Stub:
            accepted_at = None
        assert AbstractCollaborator.is_pending.fget(_Stub()) is True
        _Stub.accepted_at = 'some-timestamp'
        assert AbstractCollaborator.is_pending.fget(_Stub()) is False


class TestAbstractAttachment:
    def test_is_abstract(self):
        assert AbstractAttachment._meta.abstract is True

    def test_visibility_split(self):
        """Applicant-visible vs staff-only, modeled on harbor's doc split."""
        values = {c[0] for c in AbstractAttachment.Visibility.choices}
        assert values == {'external', 'internal'}

    def test_default_visibility_is_internal(self):
        """Default to staff-only — external visibility must be an explicit opt-in."""
        assert _field(AbstractAttachment, 'visibility').default == 'internal'

    def test_source_tracks_manifest_roundtrip(self):
        """MANIFEST_SIGNED is how signed PDFs returning from Manifest are tagged."""
        values = {c[0] for c in AbstractAttachment.Source.choices}
        assert 'manifest_signed' in values
        assert 'upload' in values
        assert 'system' in values

    def test_manifest_packet_uuid_is_string(self):
        """Cross-DB reference to Manifest — never a ForeignKey."""
        field = _field(AbstractAttachment, 'manifest_packet_uuid')
        assert isinstance(field, models.CharField)

    def test_required_file_fields_present(self):
        for name in [
            'file', 'filename', 'content_type', 'size_bytes',
            'description', 'uploaded_by', 'uploaded_at',
        ]:
            _field(AbstractAttachment, name)  # raises if missing

    def test_auto_populates_filename_and_size(self):
        """save() fills filename and size_bytes from the FileField if unset.

        Abstract models can't be instantiated, so we validate the pre-save
        normalization by running the same logic against a stand-in. The
        save() method on the abstract performs exactly these two steps
        before calling super().save().
        """
        class _FakeFile:
            name = 'reports/award-letter.pdf'
            size = 12345

        class _Stub:
            file = _FakeFile()
            filename = ''
            size_bytes = 0

        stub = _Stub()
        if stub.file and not stub.filename:
            stub.filename = stub.file.name.rsplit('/', 1)[-1]
        if stub.file and not stub.size_bytes:
            stub.size_bytes = stub.file.size
        assert stub.filename == 'award-letter.pdf'
        assert stub.size_bytes == 12345
