"""
Keel Communications — data models.

Provides entity-routed email communication for all DockLabs products.
Each product entity (Grant, FOIA Request, Organization, etc.) gets a
stable mailbox address that external parties can email directly.

Usage:
    from keel.comms.models import MailboxAddress, Thread, Message

Products integrate via GenericForeignKey on MailboxAddress and the
CommsMailboxMixin on their domain models.
"""
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# MailboxAddress
# ---------------------------------------------------------------------------
class MailboxAddress(models.Model):
    """A stable, routable email address bound to a product entity.

    Created lazily on first send or manually. The address encodes
    product, entity type, and entity ID for deterministic inbound routing.

    Example: harbor+grant-4821@mail.docklabs.ai → Harbor Grant #4821
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    address = models.EmailField(unique=True, db_index=True)
    product = models.CharField(
        max_length=50,
        help_text='Product slug: harbor, admiralty, beacon, bounty, etc.',
    )

    # Generic link to the owning entity
    entity_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE,
    )
    entity_id = models.UUIDField()
    entity = GenericForeignKey('entity_type', 'entity_id')

    display_name = models.CharField(
        max_length=255,
        help_text='Friendly sender name, e.g. "Harbor \u2013 Grant #4821".',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
        ]
        verbose_name = 'mailbox address'
        verbose_name_plural = 'mailbox addresses'

    def __str__(self):
        return f'{self.display_name} <{self.address}>'


# ---------------------------------------------------------------------------
# Thread
# ---------------------------------------------------------------------------
class Thread(models.Model):
    """Groups messages into a conversation on a mailbox.

    One mailbox can have many threads (different subjects / conversations).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(
        MailboxAddress, on_delete=models.CASCADE,
        related_name='threads',
    )
    subject = models.CharField(max_length=500)
    is_archived = models.BooleanField(default=False)
    is_read = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['mailbox', '-updated_at']),
        ]

    def __str__(self):
        return self.subject

    @property
    def latest_message(self):
        return self.messages.order_by('-sent_at').first()

    @property
    def message_count(self):
        return self.messages.count()


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------
class Message(models.Model):
    """An individual email — inbound or outbound.

    Stores enough RFC 5322 header data (Message-ID, In-Reply-To,
    References) to maintain proper threading with external mail clients.
    """

    class Direction(models.TextChoices):
        INBOUND = 'inbound', _('Inbound')
        OUTBOUND = 'outbound', _('Outbound')

    class DeliveryStatus(models.TextChoices):
        PENDING = 'pending', _('Pending')
        SENT = 'sent', _('Sent')
        DELIVERED = 'delivered', _('Delivered')
        BOUNCED = 'bounced', _('Bounced')
        FAILED = 'failed', _('Failed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(
        Thread, on_delete=models.CASCADE,
        related_name='messages',
    )
    direction = models.CharField(max_length=8, choices=Direction.choices)

    # Envelope
    from_address = models.EmailField()
    from_name = models.CharField(max_length=255, blank=True)
    to_addresses = models.JSONField(default=list)
    cc_addresses = models.JSONField(default=list)
    reply_to = models.EmailField(blank=True)

    # Content
    subject = models.CharField(max_length=500)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)

    # RFC 5322 threading headers
    message_id_header = models.CharField(
        max_length=995, unique=True, db_index=True,
        help_text='RFC 5322 Message-ID header value.',
    )
    in_reply_to_header = models.CharField(
        max_length=995, blank=True, db_index=True,
        help_text='RFC 5322 In-Reply-To header value.',
    )
    references_header = models.JSONField(
        default=list,
        help_text='RFC 5322 References header values (list of Message-IDs).',
    )

    # Timestamps
    sent_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    # Who sent it (outbound only)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    # Postmark metadata
    postmark_message_id = models.CharField(max_length=255, blank=True)
    delivery_status = models.CharField(
        max_length=12,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    delivery_detail = models.JSONField(
        default=dict, blank=True,
        help_text='Bounce info, error details, etc.',
    )

    # Full-text search (PostgreSQL)
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        ordering = ['sent_at']
        indexes = [
            models.Index(fields=['thread', 'sent_at']),
            GinIndex(fields=['search_vector'], name='comms_msg_search_gin'),
        ]

    def __str__(self):
        arrow = '\u2192' if self.direction == self.Direction.OUTBOUND else '\u2190'
        return f'{arrow} {self.from_address}: {self.subject[:60]}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update search vector after save via raw SQL (avoids infinite loop)
        if self.subject or self.body_text:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE keel_comms_message
                    SET search_vector =
                        setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(body_text, '')), 'B') ||
                        setweight(to_tsvector('english', coalesce(from_address, '')), 'C')
                    WHERE id = %s
                """, [self.pk])



# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------
class Attachment(models.Model):
    """File attached to a message."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE,
        related_name='attachments',
    )
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    file = models.FileField(upload_to='comms/attachments/%Y/%m/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['filename']

    def __str__(self):
        return self.filename


# ---------------------------------------------------------------------------
# DeadLetter
# ---------------------------------------------------------------------------
class DeadLetter(models.Model):
    """Unroutable inbound messages for manual triage.

    Captures the full Postmark webhook payload so staff can
    investigate and manually route if needed.
    """

    class Reason(models.TextChoices):
        UNROUTABLE = 'unroutable', _('Address did not match expected format')
        NO_MAILBOX = 'no_mailbox', _('No active mailbox for this address')
        PARSE_ERROR = 'parse_error', _('Failed to parse webhook payload')
        WRONG_DOMAIN = 'wrong_domain', _('Address domain does not match tenant')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_payload = models.JSONField(help_text='Full Postmark webhook body.')
    from_address = models.EmailField()
    to_address = models.EmailField()
    subject = models.CharField(max_length=500, blank=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = 'resolved' if self.resolved else 'unresolved'
        return f'[{status}] {self.from_address} \u2192 {self.to_address}'
