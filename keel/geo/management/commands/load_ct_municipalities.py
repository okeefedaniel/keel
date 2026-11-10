"""Load the 169 Connecticut municipalities and their aliases.

Idempotent: safe on every boot. Run it right after ``migrate`` in a product's
startup so the table is never empty when an importer or a form needs it.

    python manage.py load_ct_municipalities

Ownership rules:

* Municipalities are upserted on ``number``. ``slug`` is written on create
  only; an existing slug is never changed, because public URLs depend on it.
* Aliases from the fixture carry ``source='fixture'``. They are upserted, and
  a fixture alias that a later keel release drops is deleted, so a correction
  to the fixture reaches every product.
* Aliases an operator added in the admin (``source='admin'``) are never
  overwritten and never deleted, even when the fixture has the same alias.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from keel.geo.models import Municipality, MunicipalityAlias, normalize

FIXTURE = Path(__file__).resolve().parent.parent.parent / 'fixtures' / 'ct_municipalities.json'
EXPECTED_MUNICIPALITIES = 169


class Command(BaseCommand):
    help = 'Load the 169 Connecticut municipalities and their aliases (idempotent).'

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(FIXTURE.read_text())
        rows = data['municipalities']
        if len(rows) != EXPECTED_MUNICIPALITIES:
            raise CommandError(
                f'Fixture holds {len(rows)} municipalities, expected '
                f'{EXPECTED_MUNICIPALITIES}: {FIXTURE}'
            )

        created = 0
        for row in rows:
            row = dict(row)
            number, slug = row.pop('number'), row.pop('slug')
            _, was_created = Municipality.objects.update_or_create(
                number=number, defaults=row, create_defaults={**row, 'slug': slug},
            )
            created += was_created

        fixture_source = MunicipalityAlias.Source.FIXTURE
        admin_keys = {
            normalize(alias) for alias in MunicipalityAlias.objects
            .filter(source=MunicipalityAlias.Source.ADMIN).values_list('alias', flat=True)
        }
        kept, alias_created = set(), 0
        for row in data['aliases']:
            key = normalize(row['alias'])
            if key in admin_keys:
                continue
            _, was_created = MunicipalityAlias.objects.update_or_create(
                alias=row['alias'],
                defaults={
                    'municipality_id': row['municipality'],
                    'multi_town': row['multi_town'],
                    'source': fixture_source,
                },
            )
            kept.add(row['alias'])
            alias_created += was_created

        stale, _ = (
            MunicipalityAlias.objects.filter(source=fixture_source)
            .exclude(alias__in=kept).delete()
        )

        self.stdout.write(self.style.SUCCESS(
            f'Municipalities: {Municipality.objects.count()} loaded ({created} new). '
            f'Aliases: {MunicipalityAlias.objects.count()} '
            f'({alias_created} new, {stale} stale fixture aliases removed, '
            f'{len(admin_keys)} operator-owned).'
        ))
