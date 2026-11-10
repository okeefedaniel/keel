#!/usr/bin/env python3
"""Rebuild ``keel/geo/fixtures/ct_municipalities.json`` from its three sources.

The fixture is checked in; this script exists so the next refresh is a command,
not archaeology. It needs ``openpyxl`` (dev machine only, never a keel runtime
dependency) and three inputs that live outside this repo:

    python scripts/build_geo_fixture.py \\
        --geojson  ../harbor/static/data/ct-towns.geojson \\
        --workbook ../purser/docs/import/DECD-programs.xlsx \\
        --formap   ../purser/docs/import/airtable/ct-municipalities/ForMap.json

Sources and what each contributes:

* CT DOT town boundaries geojson (169 features): number, name, OBJECTID,
  county, planning region, council of governments, square miles.
* The programs workbook's ``CT Towns`` tab: village/typo -> town aliases (columns A/B and
  H/I). Identity rows, blank targets and non-town targets are skipped; a target
  written ``A/B`` becomes a ``multi_town`` alias with no municipality.
* Airtable ``ForMap`` export: ``Population2023`` joined on MunicipalityNumber.

Two deliberate departures from the workbook, both documented here so the
fixture never silently disagrees with its source:

ALIAS_CORRECTIONS — four consecutive rows of the workbook's lookup are shifted
by one (each village carries the town of the row below it). Geography is not
ambiguous for any of them, so the fixture carries the right town. If the
workbook is repaired the build fails on purpose and asks for the entry to be
removed.

COG_ABBREVIATIONS — the workbook labels both the Southeastern and the South
Central councils ``SCRCOG``. They are different bodies; the abbreviation is
derived from the council name instead.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ALIAS_CORRECTIONS = {
    # village: (workbook value, correct town)
    'Gales Ferry': ('Redding', 'Ledyard'),
    'Georgetown': ('Bozrah', 'Redding'),
    'Gilman': ('Greenwich', 'Bozrah'),
    'Glenville': ('Goshen', 'Greenwich'),
}

COG_ABBREVIATIONS = {
    'Capital Region': 'CRCOG',
    'CT Metropolitan': 'MetroCOG',
    'Lower CT River Valley': 'RiverCOG',
    'Naugatuck Valley': 'NVCOG',
    'Northeastern CT': 'NECCOG',
    'Northwest Hills': 'NHCOG',
    'South Central Regional': 'SCRCOG',
    'Southeastern CT': 'SCCOG',
    'Western CT': 'WestCOG',
}


def slugify(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def first(value):
    return value[0] if isinstance(value, list) and value else value


def build(geojson_path, workbook_path, formap_path):
    import openpyxl

    features = json.loads(Path(geojson_path).read_text())['features']
    formap = json.loads(Path(formap_path).read_text())
    population = {
        first(row['fields'].get('MunicipalityNumber')): first(row['fields'].get('Population2023'))
        for row in formap
    }

    municipalities = []
    for feature in features:
        p = feature['properties']
        cog = p['CouncilOfGovernment']
        municipalities.append({
            'number': p['MunicipalityNumber'],
            'name': p['Municipality'],
            'slug': slugify(p['Municipality']),
            'objectid': p['OBJECTID'],
            'county': p['County'],
            'planning_region': p['PlanningRegion'],
            'council_of_governments': cog,
            'cog_abbr': COG_ABBREVIATIONS[cog],
            'square_miles': round(p['SquareMiles'], 2),
            'population': population.get(p['MunicipalityNumber']),
        })
    municipalities.sort(key=lambda m: m['number'])
    numbers = {m['name']: m['number'] for m in municipalities}

    rows = list(
        openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)['CT Towns']
        .iter_rows(min_row=2, values_only=True)
    )
    pairs = {}
    for row in rows:
        for alias_col, target_col in ((0, 1), (7, 8)):
            alias, target = row[alias_col], row[target_col]
            if not alias or not target:
                continue
            alias, target = str(alias).strip(), str(target).strip()
            if alias == target:
                continue
            pairs.setdefault(alias, target)

    aliases, skipped = [], []
    for alias, target in sorted(pairs.items()):
        if alias in ALIAS_CORRECTIONS:
            expected, corrected = ALIAS_CORRECTIONS[alias]
            if target != expected:
                sys.exit(
                    f'{alias!r} now maps to {target!r} in the workbook (expected the '
                    f'known-shifted {expected!r}). The source may have been repaired: '
                    f'remove it from ALIAS_CORRECTIONS.'
                )
            target = corrected
        if '/' in target:
            aliases.append({'alias': alias, 'municipality': None, 'town': target, 'multi_town': True})
        elif target in numbers:
            aliases.append({'alias': alias, 'municipality': numbers[target], 'town': target, 'multi_town': False})
        else:
            skipped.append((alias, target))

    return {'municipalities': municipalities, 'aliases': aliases}, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--geojson', required=True)
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--formap', required=True)
    parser.add_argument(
        '--out',
        default=str(Path(__file__).resolve().parent.parent / 'keel/geo/fixtures/ct_municipalities.json'),
    )
    args = parser.parse_args()
    fixture, skipped = build(args.geojson, args.workbook, args.formap)
    Path(args.out).write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + '\n')
    print(f"{len(fixture['municipalities'])} municipalities, {len(fixture['aliases'])} aliases -> {args.out}")
    for alias, target in skipped:
        print(f'  skipped (target is not a town): {alias!r} -> {target!r}')


if __name__ == '__main__':
    main()
