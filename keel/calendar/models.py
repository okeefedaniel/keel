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
from django.utils.translation import gettext_lazy as _


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Who and what
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(app_label)s_calendar_events',
        help_text='Whose calendar the event lives on.',
    )
    event_type = models.CharField(
        max_length=100,
        help_text='Registry key, e.g. "invitation_scheduled".',
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
