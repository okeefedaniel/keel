"""
Full-text search engine for comms messages.

Enables FOIA-mandated rapid search across all email communications.
Subclasses keel.search.engine.SearchEngine for consistency with
other product search implementations.

Usage:
    from keel.comms.search import comms_search

    # Full ranked search
    results = comms_search.search('grant renewal deadline')

    # With filters
    results = comms_search.search('budget', filters={
        'direction': 'inbound',
        'thread__mailbox__product': 'harbor',
    })

    # Instant typeahead
    results = comms_search.instant_search('renew')
"""
from keel.search.engine import SearchEngine

from .models import Message


class CommsSearchEngine(SearchEngine):
    """PostgreSQL FTS over Message subject + body_text."""

    model = Message
    search_vector_field = 'search_vector'
    search_fields = {
        'subject': 'A',
        'body_text': 'B',
        'from_address': 'C',
    }
    trigram_fields = ['subject']
    instant_display_fields = [
        'subject', 'from_address', 'from_name',
        'direction', 'sent_at',
    ]

    def format_instant_result(self, row):
        return {
            'id': str(row['id']),
            'subject': row.get('subject', ''),
            'from': row.get('from_name') or row.get('from_address', ''),
            'direction': row.get('direction', ''),
            'sent_at': str(row.get('sent_at', '')),
        }

    def get_filter_kwargs(self, filters):
        """Support filtering by direction, mailbox product, and date range."""
        kwargs = {}
        if not filters:
            return kwargs

        if 'direction' in filters:
            kwargs['direction'] = filters['direction']
        if 'product' in filters:
            kwargs['thread__mailbox__product'] = filters['product']
        if 'mailbox_id' in filters:
            kwargs['thread__mailbox_id'] = filters['mailbox_id']
        if 'sent_after' in filters:
            kwargs['sent_at__gte'] = filters['sent_after']
        if 'sent_before' in filters:
            kwargs['sent_at__lte'] = filters['sent_before']

        return kwargs


# Module-level singleton
comms_search = CommsSearchEngine()
