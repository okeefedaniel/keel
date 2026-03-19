"""
Keel FOIA Search — Abstract search interface for FOIA record discovery.

Products implement concrete search by subclassing FOIASearchEngine
and registering their searchable record types.

Usage:
    from keel.foia.search import FOIASearchEngine, SearchableRecordType

    class BeaconFOIASearch(FOIASearchEngine):
        def get_record_types(self):
            return [
                SearchableRecordType(
                    name='interaction',
                    model=Interaction,
                    text_fields=['subject', 'description'],
                    company_field='company__name',
                    date_field='date',
                    zone_field='zone',
                    snapshot_builder=self._build_interaction_snapshot,
                ),
                SearchableRecordType(
                    name='note',
                    model=Note,
                    text_fields=['subject', 'content'],
                    company_field='company__name',
                    date_field='created_at__date',
                    zone_field='zone',
                    snapshot_builder=self._build_note_snapshot,
                ),
            ]
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.db.models import Q

logger = logging.getLogger(__name__)


@dataclass
class SearchableRecordType:
    """Defines how to search a specific model for FOIA-responsive records."""
    name: str
    model: type  # Django model class
    text_fields: list[str] = field(default_factory=list)  # Fields to keyword-search
    company_field: str = ''  # Lookup path for company name filtering
    contact_fields: list[str] = field(default_factory=list)  # Lookup paths for contact name filtering
    date_field: str = ''  # Field for date range filtering
    zone_field: str = 'zone'  # Field containing the FOIA zone
    excluded_zones: list[str] = field(default_factory=lambda: ['act_private'])
    snapshot_builder: Optional[Callable] = None  # Function to build snapshot text
    select_related: list[str] = field(default_factory=list)
    prefetch_related: list[str] = field(default_factory=list)


class FOIASearchEngine:
    """Abstract FOIA search engine. Subclass and implement get_record_types()."""

    def get_record_types(self) -> list[SearchableRecordType]:
        """Return list of searchable record types. Override in product."""
        raise NotImplementedError

    def pre_classify(self, zone, foia_status=None):
        """Suggest a pre-classification based on zone."""
        if zone in ('act_private',):
            return 'not_relevant'
        if foia_status == 'exempt':
            return 'likely_exempt'
        elif foia_status == 'responsive':
            return 'likely_responsive'
        elif zone == 'decd_internal':
            return 'needs_review'
        else:
            return 'likely_responsive'

    def build_keyword_q(self, record_type, keywords):
        """Build Q object for keyword search across text fields."""
        q = Q()
        for keyword in keywords:
            kw = keyword.strip()
            if not kw:
                continue
            keyword_q = Q()
            for field_path in record_type.text_fields:
                keyword_q |= Q(**{f'{field_path}__icontains': kw})
            q |= keyword_q
        return q

    def build_company_q(self, record_type, company_names):
        """Build Q for company name matching."""
        if not record_type.company_field:
            return Q()
        q = Q()
        for name in company_names:
            cn = name.strip()
            if cn:
                q |= Q(**{f'{record_type.company_field}__icontains': cn})
        return q

    def build_contact_q(self, record_type, contact_names):
        """Build Q for contact name matching."""
        if not record_type.contact_fields:
            return Q()
        q = Q()
        for name in contact_names:
            cn = name.strip()
            if not cn:
                continue
            contact_q = Q()
            for field_path in record_type.contact_fields:
                contact_q |= Q(**{f'{field_path}__icontains': cn})
            q |= contact_q
        return q

    def run_search(self, foia_request, scope, search_result_model):
        """Execute FOIA search across all registered record types.

        Args:
            foia_request: The FOIARequest instance
            scope: The FOIAScope instance with search parameters
            search_result_model: The concrete FOIASearchResult model class

        Returns:
            int: Number of results found
        """
        # Clear previous results
        search_result_model.objects.filter(foia_request=foia_request).delete()

        results_created = 0

        for rt in self.get_record_types():
            # Build combined Q
            q = Q()
            if scope.keywords:
                q |= self.build_keyword_q(rt, scope.keywords)
            if scope.company_names:
                q |= self.build_company_q(rt, scope.company_names)
            if scope.contact_names:
                q |= self.build_contact_q(rt, scope.contact_names)

            if not q:
                continue

            # Base queryset excluding private zones
            qs = rt.model.objects.filter(q)
            for excluded in rt.excluded_zones:
                qs = qs.exclude(**{rt.zone_field: excluded})

            # Date range
            if scope.date_range_start and rt.date_field:
                qs = qs.filter(**{f'{rt.date_field}__gte': scope.date_range_start})
            if scope.date_range_end and rt.date_field:
                qs = qs.filter(**{f'{rt.date_field}__lte': scope.date_range_end})

            # Optimize
            if rt.select_related:
                qs = qs.select_related(*rt.select_related)
            if rt.prefetch_related:
                qs = qs.prefetch_related(*rt.prefetch_related)

            qs = qs.distinct()

            # Create search results
            for record in qs:
                zone = getattr(record, rt.zone_field, 'shared')
                foia_status = getattr(record, 'foia_status', None)

                snapshot = ''
                metadata = {'zone': zone}
                if rt.snapshot_builder:
                    snapshot, metadata = rt.snapshot_builder(record)

                search_result_model.objects.create(
                    foia_request=foia_request,
                    record_type=rt.name,
                    record_id=record.pk,
                    record_description=str(record),
                    snapshot_content=snapshot,
                    snapshot_metadata=metadata,
                    pre_classification=self.pre_classify(zone, foia_status),
                )
                results_created += 1

        logger.info(
            'FOIA search for %s found %d results',
            foia_request.request_number, results_created,
        )
        return results_created
