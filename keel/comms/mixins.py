"""
Product model mixin for comms integration.

Add CommsMailboxMixin to any product model that participates in
external email communication. Provides lazy mailbox creation and
convenient accessors for templates.

Usage:
    class Grant(CommsMailboxMixin, models.Model):
        COMMS_PRODUCT = 'harbor'
        COMMS_ENTITY_TYPE = 'grant'

        def comms_display_name(self):
            return f'Harbor \u2013 Grant #{self.pk}'
"""
from django.contrib.contenttypes.models import ContentType


class CommsMailboxMixin:
    """Mixin for product models that have a comms mailbox.

    Subclasses must define:
        COMMS_PRODUCT: str — product slug (e.g. 'harbor')
        COMMS_ENTITY_TYPE: str — entity type slug (e.g. 'grant')
        comms_display_name() -> str — friendly name for the From header
    """

    COMMS_PRODUCT = ''
    COMMS_ENTITY_TYPE = ''

    def comms_display_name(self):
        """Override to provide a friendly sender name."""
        return f'{self.COMMS_PRODUCT.title()} \u2013 {self.COMMS_ENTITY_TYPE.title()} #{self.pk}'

    @property
    def comms_mailbox(self):
        """Get or create the MailboxAddress for this entity."""
        from keel.comms.addresses import get_or_create_mailbox
        mailbox, _ = get_or_create_mailbox(
            entity=self,
            product=self.COMMS_PRODUCT,
            entity_type_slug=self.COMMS_ENTITY_TYPE,
            display_name=self.comms_display_name(),
        )
        return mailbox

    @property
    def comms_threads(self):
        """Active threads for this entity's mailbox."""
        from keel.comms.models import MailboxAddress, Thread
        ct = ContentType.objects.get_for_model(self)
        try:
            mailbox = MailboxAddress.objects.get(
                entity_type=ct,
                entity_id=self.pk,
                is_active=True,
            )
        except MailboxAddress.DoesNotExist:
            return Thread.objects.none()
        return mailbox.threads.filter(is_archived=False)

    @property
    def comms_has_mailbox(self):
        """Check if a mailbox exists without creating one."""
        from keel.comms.models import MailboxAddress
        ct = ContentType.objects.get_for_model(self)
        return MailboxAddress.objects.filter(
            entity_type=ct,
            entity_id=self.pk,
        ).exists()
