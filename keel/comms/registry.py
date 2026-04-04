"""
Product handler registry for inbound message dispatch.

Products register handlers at startup (AppConfig.ready()) to receive
inbound messages routed to their mailboxes. This keeps all product-specific
logic out of keel.comms itself.

Usage:
    from keel.comms.registry import comms_registry, InboundHandler

    comms_registry.register(InboundHandler(
        product='harbor',
        entity_type='grant',
        on_inbound=handle_harbor_grant_inbound,
    ))

Handler signature:
    def handle_harbor_grant_inbound(message, mailbox):
        grant = mailbox.entity
        # ... product-specific logic ...
"""
import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundHandler:
    """Defines how a product handles inbound mail for an entity type."""

    product: str
    entity_type: str
    on_inbound: Callable
    description: str = ''


class CommsHandlerRegistry:
    """Registry of product inbound handlers.

    Keyed by (product, entity_type) tuples. Each pair can have
    exactly one handler.
    """

    def __init__(self):
        self._handlers: dict[tuple[str, str], InboundHandler] = {}

    def register(self, handler: InboundHandler) -> None:
        key = (handler.product, handler.entity_type)
        if key in self._handlers:
            logger.warning(
                'Comms handler for %s/%s re-registered (overwriting)',
                handler.product, handler.entity_type,
            )
        self._handlers[key] = handler

    def get_handler(self, product: str, entity_type: str) -> Optional[InboundHandler]:
        return self._handlers.get((product, entity_type))

    def dispatch(self, product: str, entity_type: str, message, mailbox) -> bool:
        """Dispatch an inbound message to the registered handler.

        Returns True if a handler was found and executed, False otherwise.
        """
        handler = self.get_handler(product, entity_type)
        if handler is None:
            logger.info(
                'No comms handler registered for %s/%s — message %s stored but not dispatched',
                product, entity_type, message.pk,
            )
            return False

        try:
            handler.on_inbound(message=message, mailbox=mailbox)
            return True
        except Exception:
            logger.exception(
                'Comms handler for %s/%s raised an exception on message %s',
                product, entity_type, message.pk,
            )
            return False

    def get_all_handlers(self) -> dict[tuple[str, str], InboundHandler]:
        return dict(self._handlers)

    def clear(self) -> None:
        """Clear all handlers. Used in testing."""
        self._handlers.clear()


# Module-level singleton — products import and register against this.
comms_registry = CommsHandlerRegistry()
