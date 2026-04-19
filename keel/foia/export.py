"""
FOIA Export Service — lets any DockLabs product one-click export records
to Admiralty (the central FOIA hub).

Products register exportable record types at startup via AppConfig.ready():

    from keel.foia.export import foia_export_registry

    foia_export_registry.register(
        product='lookout',
        record_type='testimony',
        queryset_fn=lambda: Testimony.objects.all(),
        serializer_fn=lambda t: FOIAExportRecord(
            source_product='lookout',
            record_type='testimony',
            record_id=str(t.pk),
            title=t.title,
            content=t.content,
            created_by=str(t.created_by),
            created_at=t.created_at,
            metadata={'bill_number': t.bill.number, 'position': t.position},
        ),
        display_name='Testimony',
        description='Legislative testimony documents',
    )
"""
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from django.apps import apps
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class FOIAExportRecord:
    """A record being exported for FOIA review."""
    source_product: str          # 'lookout', 'beacon', etc.
    record_type: str             # 'testimony', 'tracking_note', 'interaction', etc.
    record_id: str               # PK of the source record
    title: str                   # Human-readable title
    content: str                 # Full text content for review
    created_by: str = ''         # Author name
    created_at: Optional[datetime] = None  # When the content was created
    metadata: dict = field(default_factory=dict)  # Product-specific context


@dataclass
class ExportableType:
    """Registry entry for an exportable record type."""
    product: str
    record_type: str
    queryset_fn: Callable
    serializer_fn: Callable
    display_name: str = ''
    description: str = ''


class FOIAExportRegistry:
    """Registry of exportable record types across products.

    Each product registers its exportable types at startup:
        registry.register('lookout', 'testimony',
            queryset_fn=lambda: Testimony.objects.all(),
            serializer_fn=lambda t: FOIAExportRecord(...))
    """

    def __init__(self):
        self._registry: dict[str, ExportableType] = {}

    def register(self, product: str, record_type: str,
                 queryset_fn: Callable, serializer_fn: Callable,
                 display_name: str = '', description: str = ''):
        """Register an exportable record type."""
        key = f"{product}:{record_type}"
        self._registry[key] = ExportableType(
            product=product,
            record_type=record_type,
            queryset_fn=queryset_fn,
            serializer_fn=serializer_fn,
            display_name=display_name or record_type.replace('_', ' ').title(),
            description=description,
        )
        logger.debug('Registered FOIA exportable: %s', key)

    def get_exportable_types(self, product: str = None) -> list[ExportableType]:
        """Return registered exportable types, optionally filtered by product."""
        types = list(self._registry.values())
        if product:
            types = [t for t in types if t.product == product]
        return sorted(types, key=lambda t: (t.product, t.record_type))

    def get_type(self, product: str, record_type: str) -> Optional[ExportableType]:
        """Get a specific exportable type."""
        return self._registry.get(f"{product}:{record_type}")

    def export_record(self, product: str, record_type: str,
                      record_id: str) -> Optional[FOIAExportRecord]:
        """Serialize a single record using the registered serializer."""
        entry = self.get_type(product, record_type)
        if not entry:
            raise ValueError(f"No exportable type registered: {product}:{record_type}")

        qs = entry.queryset_fn()
        try:
            record = qs.get(pk=record_id)
        except qs.model.DoesNotExist:
            raise ValueError(f"Record not found: {product}:{record_type}:{record_id}")

        return entry.serializer_fn(record)


# Module-level singleton
foia_export_registry = FOIAExportRegistry()


def _content_hash(content: str) -> str:
    """SHA256 hash of content for deduplication."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _get_export_model():
    """Resolve the concrete FOIAExportItem model from settings."""
    model_path = getattr(settings, 'KEEL_FOIA_EXPORT_MODEL', None)
    if not model_path:
        raise RuntimeError(
            'KEEL_FOIA_EXPORT_MODEL is not set. Add it to settings: '
            "KEEL_FOIA_EXPORT_MODEL = 'myapp.FOIAExportItem'"
        )
    return apps.get_model(model_path)


def submit_to_foia(source_product: str, record_type: str, record_id: str,
                   title: str, content: str,
                   created_by: str = '', created_at=None, metadata=None,
                   submitted_by=None, foia_request_id: str = '',
                   submitter_ip: str = ''):
    """Submit a single record for FOIA review.

    Creates a FOIAExportItem in the queue for Admiralty to pick up.
    Returns the created export item.

    ``submitter_ip`` — optional client IP of the user triggering the
    export. Persisted on the queue item so FOIA review has an audit
    trail of who initiated the push, not just who authored the record.
    Pass ``request.audit_ip`` from a view (populated by
    ``keel.core.middleware.AuditMiddleware``).
    """
    ExportItem = _get_export_model()
    content_hash = _content_hash(content)

    create_kwargs = dict(
        source_product=source_product,
        record_type=record_type,
        record_id=str(record_id),
        title=title,
        content=content,
        content_hash=content_hash,
        created_by_name=created_by,
        record_created_at=created_at,
        metadata=metadata or {},
        submitted_by=submitted_by,
        foia_request_id_ref=foia_request_id,
    )
    if submitter_ip and hasattr(ExportItem, 'submitter_ip'):
        create_kwargs['submitter_ip'] = submitter_ip

    item = ExportItem.objects.create(**create_kwargs)

    logger.info(
        'FOIA export: %s:%s:%s → item %s (hash: %s...)',
        source_product, record_type, record_id,
        item.pk, content_hash[:12],
    )
    return item


def bulk_submit_to_foia(records: list[FOIAExportRecord],
                        submitted_by=None, foia_request_id: str = ''):
    """Submit multiple records at once. Returns list of created items."""
    ExportItem = _get_export_model()
    items = []

    for rec in records:
        content_hash = _content_hash(rec.content)

        # Skip duplicates
        if ExportItem.objects.filter(
            source_product=rec.source_product,
            record_type=rec.record_type,
            record_id=rec.record_id,
            foia_request_id_ref=foia_request_id,
        ).exists():
            logger.debug(
                'Skipping duplicate FOIA export: %s:%s:%s',
                rec.source_product, rec.record_type, rec.record_id,
            )
            continue

        item = ExportItem(
            source_product=rec.source_product,
            record_type=rec.record_type,
            record_id=rec.record_id,
            title=rec.title,
            content=rec.content,
            content_hash=content_hash,
            created_by_name=rec.created_by,
            record_created_at=rec.created_at,
            metadata=rec.metadata,
            submitted_by=submitted_by,
            foia_request_id_ref=foia_request_id,
        )
        items.append(item)

    created = ExportItem.objects.bulk_create(items, ignore_conflicts=True)
    logger.info('FOIA bulk export: %d records submitted', len(created))
    return created
