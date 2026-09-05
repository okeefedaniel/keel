"""
Abstract calendar models for DockLabs products.

Products subclass these to track calendar events synced to external
providers (Google Calendar, Microsoft Graph / Outlook).

Usage:
    from keel.calendar.models import AbstractCalendarEvent, AbstractCalendarSyncLog

    class CalendarEvent(AbstractCalendarEvent):
        class Meta(AbstractCalendarEvent.Meta):
            pass

    class CalendarSyncLog(AbstractCalendarSyncLog):
        class Meta(AbstractCalendarSyncLog.Meta):
            pass
"""
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.utils.translation import gettext_lazy as _

from keel.security.fields import EncryptedTextField


class AbstractCalendarEvent(models.Model):
    """Tracks a calendar event synced to an external provider.

    Uses GenericForeignKey so any product model (Invitation, GrantDeadline,
    etc.) can be linked without Keel knowing about product-specific models.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        SYNCED = 'synced', _('Synced')
        FAILED = 'failed', _('Failed')
        CANCELLED = 'cancelled', _('Cancelled')

    class Provider(models.TextChoices):
        GOOGLE = 'google', _('Google Calendar')
        MICROSOFT = 'microsoft', _('Microsoft Outlook')

    class HoldStatus(models.TextChoices):
        TENTATIVE = 'tentative', _('Tentative')
        CONFIRMED = 'confirmed', _('Confirmed')
        CANCELLED = 'cancelled', _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Who and what
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(app_label)s_calendar_events',
        help_text='Whose calendar the event lives on.',
    )
    event_type = models.CharField(
        max_length=100,
        default='calendar_hold',
        help_text=(
            'Registry key, e.g. "invitation_scheduled". Free-standing holds '
            'carry the default — they have no registry event type.'
        ),
    )

    # Event details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=500, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    all_day = models.BooleanField(default=False)

    # Provider sync
    provider = models.CharField(max_length=20, choices=Provider.choices)
    external_id = models.CharField(
        max_length=500, blank=True,
        help_text='ID returned by the external calendar API.',
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
        help_text=(
            'SYNC state — has this reached the provider yet. Not to be confused '
            'with hold_status, which is the domain state a human sees.'
        ),
    )
    hold_status = models.CharField(
        max_length=20, choices=HoldStatus.choices, default=HoldStatus.TENTATIVE,
        help_text=(
            'DOMAIN state — is the time provisionally blocked or agreed. Not to '
            'be confused with status, which is sync state.'
        ),
    )
    provider_uid = models.CharField(
        max_length=255, blank=True,
        help_text=(
            'Client-generated idempotency key sent on create (iCalUID on Google). '
            'Makes a retry or a double-submit converge on one provider event '
            'instead of two.'
        ),
    )
    external_etag = models.CharField(
        max_length=255, blank=True,
        help_text='Provider ETag at the last successful sync.',
    )
    external_updated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Provider-reported last modification, for external-wins comparison.',
    )
    revision = models.PositiveIntegerField(
        default=1,
        help_text=(
            'Bumped on every local edit and checked on save, so a stale tab or a '
            'duplicate submit is rejected rather than silently overwriting.'
        ),
    )
    attendees = models.JSONField(
        default=list, blank=True,
        help_text='External attendees: [{email, name, response_status}, ...].',
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True)
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text='Provider-specific data (meeting link, attendees, etc.).',
    )

    # Generic link to product entity (Invitation, GrantDeadline, etc.)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True,
    )
    object_id = models.UUIDField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        abstract = True
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['user', 'event_type']),
            models.Index(fields=['external_id']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['status', 'last_synced_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) - {self.start_time:%Y-%m-%d %H:%M}"


class AbstractCalendarConnection(models.Model):
    """A user's OAuth connection to one external calendar provider.

    Delegated OAuth: the token belongs to the USER, and every write Yeoman makes
    to that user's calendar authenticates as them. That makes this row, together
    with AbstractCalendarDelegation, the whole of the access-control story — the
    provider performs no check of its own.

    Tokens are stored with EncryptedTextField (KEEL_ENCRYPTION_KEYS), the same
    field that holds KeelUser.anthropic_api_key_encrypted. A refresh token is a
    long-lived read/write key to a real person's calendar; it never lands in the
    database as plain text.

        connect ──► access_token (short-lived) ──┐
                    refresh_token (long-lived) ──┴──► refresh under row lock
                                                      (a superseded refresh
                                                       token silently
                                                       disconnects the user)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(app_label)s_calendar_connections',
    )
    provider = models.CharField(
        max_length=20, choices=AbstractCalendarEvent.Provider.choices,
    )
    external_account_email = models.EmailField(
        blank=True, help_text='The account this connection authenticates as.',
    )

    access_token = EncryptedTextField(blank=True, default='')
    refresh_token = EncryptedTextField(blank=True, default='')
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list, blank=True)

    primary_calendar_id = models.CharField(max_length=255, blank=True)
    sync_token = models.TextField(
        blank=True,
        help_text=(
            "Provider delta cursor. Google answers a stale one with 410 GONE and "
            "Graph's deltaLink expires, so an invalidated cursor must trigger a "
            "bounded full resync rather than being retried."
        ),
    )

    is_active = models.BooleanField(default=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    last_sync_at = models.DateTimeField(
        null=True, blank=True, help_text='Last sync ATTEMPT, successful or not.',
    )
    last_successful_sync_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            'Last sync that actually succeeded. This is the staleness canary — a '
            'green cron over a stalled sync is the silent failure this feature is '
            'most likely to die of.'
        ),
    )
    last_sync_error = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ['user', 'provider']
        constraints = [
            UniqueConstraint(
                fields=['user', 'provider'],
                name='%(app_label)s_%(class)s_unique_user_provider',
            ),
        ]
        indexes = [
            models.Index(fields=['is_active', 'last_successful_sync_at']),
        ]

    def __str__(self):
        state = 'active' if self.is_active else 'inactive'
        return f'{self.user} | {self.get_provider_display()} [{state}]'

    @property
    def is_token_expired(self):
        """True when the access token is past its expiry (or has none)."""
        from django.utils import timezone
        if not self.access_token_expires_at:
            return True
        return self.access_token_expires_at <= timezone.now()


class AbstractCalendarDelegation(models.Model):
    """A standing grant letting *grantee* act on *grantor*'s calendar.

    SECURITY BOUNDARY, not sharing UX. A delegate's write authenticates as the
    GRANTOR using the grantor's own stored token, so the provider never
    evaluates whether the delegate should be allowed. This row is the only gate
    on writing to a real person's real calendar. Grant, use, and revocation all
    belong in the audit log.

    ``view_free_busy`` must SHAPE the response, not merely gate it: a grantee at
    that level sees start/end busy blocks and nothing else. Returning a payload
    that still carries title, location, description, attendees, provider, or
    external ids is a privacy leak, not a cosmetic bug.
    """

    class Permission(models.TextChoices):
        VIEW_FREE_BUSY = 'view_free_busy', _('See busy times only')
        VIEW_DETAILS = 'view_details', _('See event details')
        EDIT = 'edit', _('Create and edit events')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grantor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(app_label)s_calendar_delegations_granted',
        help_text='Whose calendar is being shared.',
    )
    grantee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(app_label)s_calendar_delegations_received',
        help_text='Who receives access.',
    )
    permission = models.CharField(
        max_length=20, choices=Permission.choices,
        default=Permission.VIEW_FREE_BUSY,
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set rather than deleting, so revoked grants stay auditable.',
    )

    class Meta:
        abstract = True
        ordering = ['grantor', 'grantee']
        constraints = [
            # Deliberately NOT unique_together on (grantor, grantee): that
            # cannot retain revoked grants as history without mutating rows.
            # A partial unique index on the ACTIVE row keeps one live grant per
            # pair while the audit trail accumulates behind it.
            UniqueConstraint(
                fields=['grantor', 'grantee'],
                condition=Q(revoked_at__isnull=True),
                name='%(app_label)s_%(class)s_unique_active_grant',
            ),
        ]
        indexes = [
            models.Index(fields=['grantee', 'revoked_at']),
        ]

    def __str__(self):
        state = 'revoked' if self.revoked_at else self.get_permission_display()
        return f'{self.grantor} -> {self.grantee} [{state}]'

    @property
    def is_active(self):
        return self.revoked_at is None

    def allows_edit(self):
        return self.is_active and self.permission == self.Permission.EDIT

    def allows_details(self):
        return self.is_active and self.permission in (
            self.Permission.VIEW_DETAILS, self.Permission.EDIT,
        )


class AbstractCalendarSyncLog(models.Model):
    """Tracks calendar sync attempts for debugging and metrics.

    Parallels AbstractNotificationLog from keel.notifications.models.
    """

    class Action(models.TextChoices):
        PUSH = 'push', _('Push')
        UPDATE = 'update', _('Update')
        CANCEL = 'cancel', _('Cancel')
        AVAILABILITY = 'availability', _('Availability Check')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='+',
    )
    event_type = models.CharField(max_length=100)
    action = models.CharField(max_length=20, choices=Action.choices)
    provider = models.CharField(max_length=20)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'event_type', '-created_at']),
        ]

    def __str__(self):
        status = 'OK' if self.success else 'FAIL'
        return f"{self.user} | {self.action} | {self.provider} [{status}]"
