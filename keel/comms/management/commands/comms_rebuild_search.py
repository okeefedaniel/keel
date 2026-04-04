"""Rebuild search vectors for all comms messages.

Run after data import or periodically to keep FTS indexes current.

Usage:
    python manage.py comms_rebuild_search
    python manage.py comms_rebuild_search --mailbox harbor+grant-4821@mail.docklabs.ai
"""
from django.core.management.base import BaseCommand

from keel.comms.models import Message
from keel.comms.search import comms_search


class Command(BaseCommand):
    help = 'Rebuild full-text search vectors for comms messages.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mailbox',
            type=str,
            help='Only rebuild for a specific mailbox address.',
        )

    def handle(self, *args, **options):
        qs = None
        if options['mailbox']:
            qs = Message.objects.filter(
                thread__mailbox__address=options['mailbox'],
            )
            count = qs.count()
            self.stdout.write(f'Rebuilding search vectors for {count} messages in {options["mailbox"]}...')
        else:
            count = Message.objects.count()
            self.stdout.write(f'Rebuilding search vectors for all {count} messages...')

        updated = comms_search.update_search_vectors(queryset=qs)
        self.stdout.write(self.style.SUCCESS(f'Updated {updated} search vectors.'))
