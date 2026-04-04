"""
Inbound address parsing and thread resolution.

Parses the structured local-part format:
    {product}+{entity_type}-{entity_id}@{mail_domain}

Examples:
    harbor+grant-4821@mail.docklabs.ai  → product=harbor, entity_type=grant, id=4821
    admiralty+request-0337@mail.docklabs.ai → product=admiralty, entity_type=request, id=337
"""
import re
from dataclasses import dataclass

from .conf import COMMS_MAIL_DOMAIN

LOCAL_PATTERN = re.compile(
    r'^(?P<product>[a-z]+)\+(?P<entity_type>[a-z]+)-(?P<entity_id>\d+)$'
)


@dataclass(frozen=True)
class ParsedAddress:
    product: str
    entity_type: str
    entity_id: int
    raw: str


def parse_address(address: str) -> ParsedAddress | None:
    """Parse a structured mailbox address into its components.

    Returns None if the address doesn't match the expected format
    or belongs to a different mail domain (wrong tenant).
    """
    address = address.lower().strip()
    local, _, domain = address.partition('@')

    if domain != COMMS_MAIL_DOMAIN:
        return None

    match = LOCAL_PATTERN.match(local)
    if not match:
        return None

    return ParsedAddress(
        product=match.group('product'),
        entity_type=match.group('entity_type'),
        entity_id=int(match.group('entity_id')),
        raw=address,
    )


def resolve_thread(mailbox, in_reply_to, references, subject):
    """Find or create a Thread for an inbound message.

    Resolution order:
    1. Match In-Reply-To header against existing Message.message_id_header
    2. Match any References header against existing messages
    3. Create a new Thread on the mailbox
    """
    from .models import Message, Thread

    # 1. Try In-Reply-To
    if in_reply_to:
        try:
            parent = Message.objects.select_related('thread').get(
                message_id_header=in_reply_to,
            )
            return parent.thread
        except Message.DoesNotExist:
            pass

    # 2. Try References (most recent first)
    if references:
        ref_list = references if isinstance(references, list) else references.split()
        for ref in reversed(ref_list):
            try:
                parent = Message.objects.select_related('thread').get(
                    message_id_header=ref.strip(),
                )
                return parent.thread
            except Message.DoesNotExist:
                continue

    # 3. New thread
    return Thread.objects.create(
        mailbox=mailbox,
        subject=subject or '(no subject)',
        is_read=False,
    )
