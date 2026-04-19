"""Abstract models for the notification preference system.

Products subclass these alongside the existing AbstractNotification
from keel.core.models.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AbstractNotificationPreference(models.Model):
    """Per-user, per-notification-type channel preferences.

    Users can control which channels (in_app, email, sms) they receive
    for each notification type, or mute it entirely.

    If no preference record exists for a user+type combo, the defaults
    from the NotificationType registry are used.

    Usage:
        class NotificationPreference(AbstractNotificationPreference):
            class Meta(AbstractNotificationPreference.Meta):
                pass
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='%(app_label)s_notification_preferences',
    )
    notification_type = models.CharField(
        max_length=100,
        help_text='Registry key of the notification type.',
    )

    # Channel toggles
    channel_in_app = models.BooleanField(
        default=True,
        verbose_name=_('In-app notifications'),
    )
    channel_email = models.BooleanField(
        default=True,
        verbose_name=_('Email notifications'),
    )
    channel_sms = models.BooleanField(
        default=False,
        verbose_name=_('SMS notifications'),
    )
    channel_boswell = models.BooleanField(
        default=False,
        verbose_name=_('OpenClaw notifications'),
    )

    # Full mute (overrides all channels)
    is_muted = models.BooleanField(
        default=False,
        verbose_name=_('Mute this notification'),
        help_text='Completely disable this notification type.',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        unique_together = [('user', 'notification_type')]
        ordering = ['notification_type']

    def __str__(self):
        status = 'muted' if self.is_muted else 'active'
        channels = []
        if self.channel_in_app:
            channels.append('app')
        if self.channel_email:
            channels.append('email')
        if self.channel_sms:
            channels.append('sms')
        if self.channel_boswell:
            channels.append('boswell')
        return f'{self.user} | {self.notification_type} | {status} [{",".join(channels)}]'


class AbstractNotificationLog(models.Model):
    """Tracks which notifications were sent via which channel.

    Useful for debugging, metrics, and preventing duplicate sends.
    Products can optionally subclass this for delivery tracking.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='+',
    )
    notification_type = models.CharField(max_length=100)
    channel = models.CharField(max_length=20)  # 'in_app', 'email', 'sms'
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'notification_type', '-created_at']),
        ]

    def __str__(self):
        status = 'OK' if self.success else 'FAIL'
        return f'{self.recipient} | {self.notification_type} | {self.channel} [{status}]'
