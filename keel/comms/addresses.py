"""
Mailbox address generation and lazy creation.

Provides the canonical way to generate deterministic email addresses
and get-or-create MailboxAddress records for product entities.
"""
import uuid

from django.contrib.contenttypes.models import ContentType

from .conf import COMMS_MAIL_DOMAIN


def generate_address(product: str, entity_type: str, entity_id) -> str:
    """Build the canonical email address for an entity.

    Args:
        product: Product slug (e.g. 'harbor').
        entity_type: Entity type slug (e.g. 'grant').
        entity_id: The entity's PK (int or UUID — stringified to the
            integer portion for the address format).
    """
    # For UUID PKs, use the integer representation for shorter addresses.
    # If it's already an int, use it directly.
    if isinstance(entity_id, uuid.UUID):
        entity_id = entity_id.int % 10_000_000  # 7-digit deterministic hash
    return f'{product}+{entity_type}-{entity_id}@{COMMS_MAIL_DOMAIN}'


def generate_message_id(domain: str | None = None) -> str:
    """Generate an RFC 5322 Message-ID header value."""
    domain = domain or COMMS_MAIL_DOMAIN
    return f'<{uuid.uuid4()}@{domain}>'


def get_or_create_mailbox(entity, product: str, entity_type_slug: str,
                          display_name: str):
    """Get or create a MailboxAddress for a product entity.

    This is the primary API for products to obtain a mailbox.
    Called lazily on first send or explicitly from the UI.

    Args:
        entity: The Django model instance (e.g. a Grant).
        product: Product slug.
        entity_type_slug: Short type name for the address (e.g. 'grant').
        display_name: Friendly name for the From header.

    Returns:
        (MailboxAddress, created) tuple.
    """
    from .models import MailboxAddress

    ct = ContentType.objects.get_for_model(entity)
    address = generate_address(product, entity_type_slug, entity.pk)

    return MailboxAddress.objects.get_or_create(
        address=address,
        defaults={
            'product': product,
            'entity_type': ct,
            'entity_id': entity.pk,
            'display_name': display_name,
        },
    )
