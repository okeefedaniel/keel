"""Seed demo communication threads on existing mailboxes.

Creates realistic-looking email threads for demo and development.
Operates on any MailboxAddress that already exists — run after
your product's demo seeder has created entities and mailboxes.

Usage:
    python manage.py seed_demo_comms
    python manage.py seed_demo_comms --product harbor
    python manage.py seed_demo_comms --mailbox admiralty+request-337@mail.docklabs.ai
"""
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from keel.comms.models import MailboxAddress, Message, Thread

# Realistic demo conversations
THREADS = [
    {
        'subject': 'Document request — additional records needed',
        'messages': [
            {
                'direction': 'inbound',
                'from_name': 'Margaret Chen',
                'from_address': 'margaret.chen@example.com',
                'body_text': (
                    'Hello,\n\n'
                    'I am writing to follow up on my original request. I believe there may be '
                    'additional records from the 2024 fiscal year that were not included in the '
                    'initial search. Specifically, I am looking for any correspondence between '
                    'the department and external auditors during Q3 2024.\n\n'
                    'Could you please expand the scope of the search to include these records?\n\n'
                    'Thank you,\n'
                    'Margaret Chen'
                ),
                'hours_ago': 72,
            },
            {
                'direction': 'outbound',
                'body_text': (
                    'Ms. Chen,\n\n'
                    'Thank you for your follow-up. I have noted your request to expand the search '
                    'scope to include Q3 2024 auditor correspondence. Our team will conduct an '
                    'additional search and include any responsive records in the final package.\n\n'
                    'We expect to have the expanded results within 3 business days.\n\n'
                    'Best regards'
                ),
                'hours_ago': 48,
            },
            {
                'direction': 'inbound',
                'from_name': 'Margaret Chen',
                'from_address': 'margaret.chen@example.com',
                'body_text': (
                    'Thank you for the prompt response. I appreciate the team\'s diligence '
                    'on this matter. I will await the expanded results.\n\n'
                    'Best,\n'
                    'Margaret'
                ),
                'hours_ago': 44,
            },
        ],
    },
    {
        'subject': 'Re: Timeline for response',
        'messages': [
            {
                'direction': 'inbound',
                'from_name': 'David Park',
                'from_address': 'dpark@newsoutlet.com',
                'body_text': (
                    'Good morning,\n\n'
                    'I wanted to check on the status of my request submitted two weeks ago. '
                    'I understand there is a statutory deadline approaching and wanted to '
                    'confirm that the response is on track.\n\n'
                    'Please let me know if there are any issues or if additional time is needed.\n\n'
                    'David Park\n'
                    'Staff Reporter'
                ),
                'hours_ago': 24,
            },
            {
                'direction': 'outbound',
                'body_text': (
                    'Mr. Park,\n\n'
                    'Your request is currently in the review phase. We have identified '
                    'the responsive records and our reviewing attorney is completing the '
                    'exemption analysis. We are on track to respond within the statutory '
                    'deadline.\n\n'
                    'You will receive the complete response package by end of week.\n\n'
                    'Regards'
                ),
                'hours_ago': 20,
            },
        ],
    },
    {
        'subject': 'Budget clarification needed',
        'messages': [
            {
                'direction': 'inbound',
                'from_name': 'Sarah Williams',
                'from_address': 'swilliams@community-foundation.org',
                'body_text': (
                    'Hi,\n\n'
                    'I noticed that line item 4.2 in our submitted budget does not match '
                    'the narrative description in Section C. The budget shows $45,000 for '
                    'equipment but the narrative references $52,000.\n\n'
                    'We\'d like to submit a corrected budget page. Should I email it to '
                    'this address or upload through the portal?\n\n'
                    'Thanks,\n'
                    'Sarah Williams\n'
                    'Grants Manager, Community Foundation'
                ),
                'hours_ago': 8,
            },
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed demo communication threads on existing mailboxes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--product', type=str, default='',
            help='Only seed for mailboxes in this product.',
        )
        parser.add_argument(
            '--mailbox', type=str, default='',
            help='Only seed for this specific mailbox address.',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Delete existing demo threads before seeding.',
        )

    def handle(self, *args, **options):
        mailboxes = MailboxAddress.objects.filter(is_active=True)

        if options['product']:
            mailboxes = mailboxes.filter(product=options['product'])
        if options['mailbox']:
            mailboxes = mailboxes.filter(address=options['mailbox'])

        if not mailboxes.exists():
            self.stdout.write(self.style.WARNING(
                'No active mailboxes found. Visit a detail page first to '
                'trigger lazy mailbox creation, or specify --product/--mailbox.'
            ))
            return

        for mailbox in mailboxes:
            if options['clear']:
                deleted, _ = Thread.objects.filter(mailbox=mailbox).delete()
                if deleted:
                    self.stdout.write(f'  Cleared {deleted} objects from {mailbox.address}')

            self._seed_mailbox(mailbox)

        self.stdout.write(self.style.SUCCESS('Demo comms data seeded.'))

    def _seed_mailbox(self, mailbox):
        now = timezone.now()

        for thread_data in THREADS:
            # Skip if a thread with this subject already exists
            if Thread.objects.filter(
                mailbox=mailbox,
                subject=thread_data['subject'],
            ).exists():
                self.stdout.write(f'  {mailbox.address}: "{thread_data["subject"]}" already exists, skipping')
                continue

            thread = Thread.objects.create(
                mailbox=mailbox,
                subject=thread_data['subject'],
                is_read=False,
            )

            prev_message = None
            for msg_data in thread_data['messages']:
                sent_at = now - timedelta(hours=msg_data['hours_ago'])
                msg_id = f'<{uuid.uuid4()}@demo.docklabs.ai>'

                in_reply_to = prev_message.message_id_header if prev_message else ''
                references = []
                if prev_message:
                    references = list(prev_message.references_header or [])
                    references.append(prev_message.message_id_header)

                if msg_data['direction'] == 'inbound':
                    from_addr = msg_data['from_address']
                    from_name = msg_data['from_name']
                    to_addrs = [{'email': mailbox.address}]
                else:
                    from_addr = mailbox.address
                    from_name = mailbox.display_name
                    # Reply to the original sender
                    first_inbound = next(
                        (m for m in thread_data['messages'] if m['direction'] == 'inbound'),
                        None,
                    )
                    to_addrs = [{'email': first_inbound['from_address']}] if first_inbound else []

                msg = Message.objects.create(
                    thread=thread,
                    direction=msg_data['direction'],
                    from_address=from_addr,
                    from_name=from_name,
                    to_addresses=to_addrs,
                    subject=thread_data['subject'],
                    body_text=msg_data['body_text'],
                    body_html=f'<pre style="font-family: sans-serif;">{msg_data["body_text"]}</pre>',
                    message_id_header=msg_id,
                    in_reply_to_header=in_reply_to,
                    references_header=references,
                    sent_at=sent_at,
                    delivery_status=(
                        Message.DeliveryStatus.DELIVERED
                        if msg_data['direction'] == 'inbound'
                        else Message.DeliveryStatus.SENT
                    ),
                )
                prev_message = msg

            # Update thread timestamp to latest message
            latest = thread.messages.order_by('-sent_at').first()
            if latest:
                thread.updated_at = latest.sent_at
                thread.save(update_fields=['updated_at'])

            self.stdout.write(
                f'  {mailbox.address}: created thread "{thread_data["subject"]}" '
                f'({len(thread_data["messages"])} messages)'
            )
