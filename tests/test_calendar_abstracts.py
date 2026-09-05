"""Field-shape pins for the calendar abstracts.

`AbstractCalendarConnection` and `AbstractCalendarDelegation` are new; the
`AbstractCalendarEvent` additions support hold CRUD and provider sync. Consumers
(yeoman, and beacon which already subclasses AbstractCalendarEvent) build
concrete tables on these, so the shape is a contract.

Introspection only, matching test_project_lifecycle_abstracts.py and
test_tag_group_abstracts.py — no concrete subclasses needed. Behavioral tests for
the constraints live in the consumer, where a real table exists.
"""
from django.db import models

from keel.security.fields import EncryptedTextField

from keel.calendar.models import (
    AbstractCalendarConnection,
    AbstractCalendarDelegation,
    AbstractCalendarEvent,
)


def _field(model, name):
    return model._meta.get_field(name)


class _Connection:
    """Stand-in carrying the real property object.

    Django refuses to instantiate an abstract model, so bind the actual
    descriptor to a plain object to exercise its logic directly.
    """
    is_token_expired = AbstractCalendarConnection.is_token_expired

    def __init__(self, access_token_expires_at=None):
        self.access_token_expires_at = access_token_expires_at


class _Delegation:
    """Stand-in carrying the real property and methods (see _Connection)."""
    Permission = AbstractCalendarDelegation.Permission
    is_active = AbstractCalendarDelegation.is_active
    allows_edit = AbstractCalendarDelegation.allows_edit
    allows_details = AbstractCalendarDelegation.allows_details

    def __init__(self, permission, revoked_at=None):
        self.permission = permission
        self.revoked_at = revoked_at


def _constraint(model, suffix):
    for c in model._meta.constraints:
        if c.name.endswith(suffix):
            return c
    raise AssertionError(
        f'no constraint ending {suffix!r} on {model.__name__}; '
        f'found {[c.name for c in model._meta.constraints]}'
    )


class TestAbstractCalendarConnection:
    def test_is_abstract(self):
        assert AbstractCalendarConnection._meta.abstract is True

    def test_required_fields_present(self):
        for name in ['id', 'user', 'provider', 'external_account_email',
                     'access_token', 'refresh_token', 'access_token_expires_at',
                     'scopes', 'primary_calendar_id', 'sync_token', 'is_active',
                     'connected_at', 'last_sync_at', 'last_successful_sync_at',
                     'last_sync_error']:
            _field(AbstractCalendarConnection, name)  # raises if missing

    def test_uuid_primary_key(self):
        pk = _field(AbstractCalendarConnection, 'id')
        assert isinstance(pk, models.UUIDField)
        assert pk.primary_key is True

    def test_tokens_are_encrypted_at_rest(self):
        """A refresh token is a long-lived read/write key to a real person's
        calendar. It must never sit in the database as plain text."""
        for name in ['access_token', 'refresh_token']:
            assert isinstance(_field(AbstractCalendarConnection, name),
                              EncryptedTextField), f'{name} is not encrypted'

    def test_provider_choices_match_the_event_model(self):
        f = _field(AbstractCalendarConnection, 'provider')
        assert f.choices == AbstractCalendarEvent.Provider.choices

    def test_one_connection_per_user_per_provider(self):
        c = _constraint(AbstractCalendarConnection, 'unique_user_provider')
        assert list(c.fields) == ['user', 'provider']

    def test_has_a_staleness_canary_distinct_from_last_attempt(self):
        """last_sync_at records an ATTEMPT; last_successful_sync_at records a
        success. Only the second one can tell you a green cron is running over
        a sync that silently stopped returning changes."""
        assert _field(AbstractCalendarConnection, 'last_sync_at') is not None
        assert _field(AbstractCalendarConnection, 'last_successful_sync_at') is not None

    def test_is_token_expired_treats_a_missing_expiry_as_expired(self):
        assert _Connection(access_token_expires_at=None).is_token_expired is True

    def test_is_token_expired_is_false_for_a_future_expiry(self):
        from datetime import timedelta

        from django.utils import timezone
        conn = _Connection(timezone.now() + timedelta(hours=1))
        assert conn.is_token_expired is False

    def test_is_token_expired_is_true_for_a_past_expiry(self):
        from datetime import timedelta

        from django.utils import timezone
        conn = _Connection(timezone.now() - timedelta(seconds=1))
        assert conn.is_token_expired is True


class TestAbstractCalendarDelegation:
    def test_is_abstract(self):
        assert AbstractCalendarDelegation._meta.abstract is True

    def test_required_fields_present(self):
        for name in ['id', 'grantor', 'grantee', 'permission', 'granted_by',
                     'granted_at', 'revoked_at']:
            _field(AbstractCalendarDelegation, name)  # raises if missing

    def test_permission_levels(self):
        assert [v for v, _ in AbstractCalendarDelegation.Permission.choices] == [
            'view_free_busy', 'view_details', 'edit',
        ]

    def test_active_grant_uniqueness_is_partial_not_unique_together(self):
        """The constraint must be conditional on revoked_at IS NULL.

        A plain unique_together on (grantor, grantee) cannot retain revoked
        grants as history without mutating rows — and this model is a security
        boundary whose revocations have to stay auditable. If this test fails
        because someone 'simplified' it back to unique_together, that is the
        regression, not the test.
        """
        c = _constraint(AbstractCalendarDelegation, 'unique_active_grant')
        assert list(c.fields) == ['grantor', 'grantee']
        assert c.condition is not None, 'constraint is unconditional'
        assert 'revoked_at' in str(c.condition)
        assert 'isnull' in str(c.condition).lower()

    def test_grantor_and_grantee_have_distinct_related_names(self):
        grantor = _field(AbstractCalendarDelegation, 'grantor')
        grantee = _field(AbstractCalendarDelegation, 'grantee')
        assert grantor.remote_field.related_name != grantee.remote_field.related_name

    def test_revocation_is_soft(self):
        f = _field(AbstractCalendarDelegation, 'revoked_at')
        assert f.null is True

    def test_permission_helpers(self):
        P = AbstractCalendarDelegation.Permission
        free_busy = _Delegation(P.VIEW_FREE_BUSY)
        details = _Delegation(P.VIEW_DETAILS)
        editor = _Delegation(P.EDIT)

        assert free_busy.allows_edit() is False
        assert free_busy.allows_details() is False
        assert details.allows_edit() is False
        assert details.allows_details() is True
        assert editor.allows_edit() is True
        assert editor.allows_details() is True

    def test_a_revoked_grant_allows_nothing(self):
        from django.utils import timezone
        revoked = _Delegation(
            AbstractCalendarDelegation.Permission.EDIT, revoked_at=timezone.now(),
        )
        assert revoked.is_active is False
        assert revoked.allows_edit() is False
        assert revoked.allows_details() is False


class TestAbstractCalendarEventAdditions:
    def test_new_fields_present(self):
        for name in ['hold_status', 'provider_uid', 'external_etag',
                     'external_updated_at', 'revision', 'attendees']:
            _field(AbstractCalendarEvent, name)  # raises if missing

    def test_hold_status_is_domain_state_defaulting_to_tentative(self):
        f = _field(AbstractCalendarEvent, 'hold_status')
        assert f.default == AbstractCalendarEvent.HoldStatus.TENTATIVE
        assert [v for v, _ in AbstractCalendarEvent.HoldStatus.choices] == [
            'tentative', 'confirmed', 'cancelled',
        ]

    def test_status_and_hold_status_are_different_axes(self):
        """`status` is sync state, `hold_status` is domain state. Same model,
        similar word — the help_text on each has to say which."""
        sync = _field(AbstractCalendarEvent, 'status')
        hold = _field(AbstractCalendarEvent, 'hold_status')
        assert 'SYNC' in sync.help_text
        assert 'DOMAIN' in hold.help_text
        assert set(v for v, _ in sync.choices) != set(v for v, _ in hold.choices)

    def test_event_type_defaults_so_a_free_standing_hold_can_omit_it(self):
        f = _field(AbstractCalendarEvent, 'event_type')
        assert f.default == 'calendar_hold'

    def test_revision_starts_at_one(self):
        f = _field(AbstractCalendarEvent, 'revision')
        assert isinstance(f, models.PositiveIntegerField)
        assert f.default == 1

    def test_attendees_defaults_to_an_empty_list(self):
        f = _field(AbstractCalendarEvent, 'attendees')
        assert isinstance(f, models.JSONField)
        assert f.default is list

    def test_provider_uid_is_the_idempotency_key(self):
        f = _field(AbstractCalendarEvent, 'provider_uid')
        assert isinstance(f, models.CharField)
        assert f.blank is True
