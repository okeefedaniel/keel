"""Tests for keel.geo: the suite's shared Connecticut town reference.

What these protect:

* the fixture's shape (169 towns, numbers 1..169, unique slugs);
* ``number`` + ``slug`` stability, because every product database holds its
  own copy of the table and public URLs are built from the slug;
* the ``resolve`` contract the Purser importer and Beacon's Airtable import
  both build on (exact name, alias, multi-town, unknown);
* the loader's ownership rules (idempotent, fixture corrections propagate,
  operator-added aliases are never touched).
"""
import json
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from keel.geo.management.commands.load_ct_municipalities import FIXTURE
from keel.geo.models import MULTI_TOWN, Municipality, MunicipalityAlias

SNAPSHOT = Path(__file__).parent / 'snapshots' / 'geo_number_slug.txt'


def load():
    out = StringIO()
    call_command('load_ct_municipalities', stdout=out)
    return out.getvalue()


class FixtureTests(TestCase):
    """The checked-in fixture, read straight from disk."""

    @classmethod
    def setUpTestData(cls):
        cls.data = json.loads(FIXTURE.read_text())

    def test_169_towns_numbered_1_to_169(self):
        numbers = [m['number'] for m in self.data['municipalities']]
        self.assertEqual(sorted(numbers), list(range(1, 170)))

    def test_names_and_slugs_are_unique(self):
        towns = self.data['municipalities']
        self.assertEqual(len({m['name'] for m in towns}), 169)
        self.assertEqual(len({m['slug'] for m in towns}), 169)

    def test_number_slug_pairs_never_change(self):
        # Each product database holds its own copy of this table and
        # dokeefect.com builds public URLs from the slug. If this fails you
        # changed a number or a slug that is already in production: revert the
        # fixture. Only a brand-new municipality may extend the snapshot.
        current = ''.join(f"{m['number']} {m['slug']}\n" for m in self.data['municipalities'])
        self.assertEqual(current, SNAPSHOT.read_text())

    def test_every_town_has_population_and_region(self):
        for town in self.data['municipalities']:
            with self.subTest(town=town['name']):
                self.assertGreater(town['population'], 0)
                self.assertTrue(town['county'])
                self.assertTrue(town['cog_abbr'])

    def test_alias_points_at_a_town_or_is_multi_town_never_both(self):
        numbers = {m['number'] for m in self.data['municipalities']}
        for alias in self.data['aliases']:
            with self.subTest(alias=alias['alias']):
                if alias['multi_town']:
                    self.assertIsNone(alias['municipality'])
                else:
                    self.assertIn(alias['municipality'], numbers)

    def test_no_alias_shadows_a_town_name(self):
        names = {m['name'].casefold() for m in self.data['municipalities']}
        shadowing = [a['alias'] for a in self.data['aliases'] if a['alias'].casefold() in names]
        self.assertEqual(shadowing, [])

    def test_two_councils_that_share_initials_keep_distinct_abbreviations(self):
        # The source workbook labels both SCRCOG; they are different bodies.
        by_name = {m['name']: m['cog_abbr'] for m in self.data['municipalities']}
        self.assertEqual(by_name['New London'], 'SCCOG')
        self.assertEqual(by_name['New Haven'], 'SCRCOG')


class ResolveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load()

    def test_exact_name(self):
        town, reason = Municipality.resolve('Killingly')
        self.assertEqual((town.name, reason), ('Killingly', None))

    def test_name_ignores_case_and_whitespace(self):
        for text in ('  east   haddam ', 'EAST HADDAM', 'East Haddam'):
            with self.subTest(text=text):
                town, reason = Municipality.resolve(text)
                self.assertEqual((town.name, reason), ('East Haddam', None))

    def test_village_alias_resolves_to_its_town(self):
        town, reason = Municipality.resolve('Dayville')
        self.assertEqual((town.name, reason), ('Killingly', None))

    def test_alias_ignores_case(self):
        town, _ = Municipality.resolve('dayville')
        self.assertEqual(town.name, 'Killingly')

    def test_multi_town_alias_resolves_to_no_town_with_a_reason(self):
        self.assertEqual(Municipality.resolve('Mystic'), (None, MULTI_TOWN))

    def test_unknown_text_is_left_for_the_caller_to_classify(self):
        for text in ('Statewide', 'Other (Boston, MA)', 'Springfield'):
            with self.subTest(text=text):
                self.assertEqual(Municipality.resolve(text), (None, None))

    def test_blank_values(self):
        for text in (None, '', '   '):
            with self.subTest(text=text):
                self.assertEqual(Municipality.resolve(text), (None, None))

    def test_aliases_the_source_workbook_had_shifted_by_one_row(self):
        # See scripts/build_geo_fixture.py ALIAS_CORRECTIONS.
        expected = {
            'Gales Ferry': 'Ledyard',
            'Georgetown': 'Redding',
            'Gilman': 'Bozrah',
            'Glenville': 'Greenwich',
        }
        for alias, town_name in expected.items():
            with self.subTest(alias=alias):
                town, reason = Municipality.resolve(alias)
                self.assertEqual((town.name, reason), (town_name, None))

    def test_bulk_resolver_agrees_with_resolve(self):
        resolver = Municipality.objects.resolver()
        samples = [
            'Killingly', ' east  haddam ', 'Dayville', 'dayville', 'Mystic',
            'Statewide', '', None, 'Gales Ferry', 'Winsted', 'Storrs Mansfield',
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(resolver(text), Municipality.resolve(text))

    def test_bulk_resolver_costs_two_queries_however_many_rows(self):
        with self.assertNumQueries(2):
            resolver = Municipality.objects.resolver()
            for _ in range(500):
                resolver('Dayville')
                resolver('Nowhere')


class LoaderTests(TestCase):
    def test_loads_169_towns_and_the_fixture_aliases(self):
        output = load()
        self.assertEqual(Municipality.objects.count(), 169)
        fixture_aliases = len(json.loads(FIXTURE.read_text())['aliases'])
        self.assertEqual(MunicipalityAlias.objects.count(), fixture_aliases)
        self.assertFalse(MunicipalityAlias.objects.exclude(source='fixture').exists())
        self.assertIn('169 loaded (169 new)', output)

    def test_second_run_changes_nothing(self):
        load()
        before = list(MunicipalityAlias.objects.values_list('pk', 'alias', 'municipality_id'))
        output = load()
        self.assertEqual(Municipality.objects.count(), 169)
        self.assertEqual(
            list(MunicipalityAlias.objects.values_list('pk', 'alias', 'municipality_id')), before,
        )
        self.assertIn('(0 new)', output)
        self.assertIn('0 new, 0 stale', output)

    def test_reload_restores_reference_data_but_never_rewrites_a_slug(self):
        load()
        Municipality.objects.filter(number=1).update(population=1, slug='andover-renamed')
        load()
        andover = Municipality.objects.get(number=1)
        self.assertGreater(andover.population, 1)
        self.assertEqual(andover.slug, 'andover-renamed')

    def test_operator_alias_survives_a_reload(self):
        load()
        MunicipalityAlias.objects.create(
            alias='Whitneyville', municipality_id=Municipality.objects.get(name='Hamden').pk,
        )
        load()
        town, _ = Municipality.resolve('Whitneyville')
        self.assertEqual(town.name, 'Hamden')
        self.assertEqual(MunicipalityAlias.objects.get(alias='Whitneyville').source, 'admin')

    def test_operator_alias_wins_over_the_same_alias_in_the_fixture(self):
        load()
        MunicipalityAlias.objects.filter(alias='Dayville').delete()
        putnam = Municipality.objects.get(name='Putnam')
        MunicipalityAlias.objects.create(alias='dayville', municipality=putnam)
        load()
        self.assertEqual(MunicipalityAlias.objects.filter(alias__iexact='dayville').count(), 1)
        self.assertEqual(Municipality.resolve('Dayville')[0], putnam)

    def test_fixture_alias_dropped_by_a_later_release_is_removed(self):
        load()
        MunicipalityAlias.objects.create(
            alias='Retired Village', municipality_id=1, source='fixture',
        )
        output = load()
        self.assertFalse(MunicipalityAlias.objects.filter(alias='Retired Village').exists())
        self.assertIn('1 stale fixture aliases removed', output)


class AliasModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load()

    def test_alias_needs_a_town_unless_it_is_multi_town(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MunicipalityAlias.objects.create(alias='Nowhere', municipality=None, multi_town=False)

    def test_multi_town_alias_cannot_also_name_a_town(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MunicipalityAlias.objects.create(alias='Both', municipality_id=1, multi_town=True)

    def test_alias_is_stored_trimmed(self):
        alias = MunicipalityAlias.objects.create(alias='  Fair   Haven ', municipality_id=93)
        self.assertEqual(alias.alias, 'Fair Haven')
        self.assertEqual(Municipality.resolve('fair haven')[0].number, 93)

    def test_primary_key_is_the_municipality_number(self):
        self.assertEqual(Municipality._meta.pk.name, 'number')
        self.assertEqual(Municipality.objects.get(pk=135).name, 'Stamford')
