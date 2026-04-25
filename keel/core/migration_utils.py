"""Helpers for writing idempotent ``RunPython`` data migrations.

A non-idempotent data migration that re-runs (manual ``migrate <app> zero``,
restored DB snapshot with a stale ``django_migrations`` row, deploy crashloop
that re-applies migrations) silently accumulates duplicates. Idempotency must
live in the migration itself when the data model legitimately allows multiple
rows per key (e.g. assignment history).
"""
from __future__ import annotations

from typing import Iterable, Sequence


def idempotent_backfill(model, key_fields: Sequence[str], rows: Iterable) -> int:
    """Bulk-create ``rows`` skipping any whose ``key_fields`` tuple already exists.

    ``model`` is a historical model from ``apps.get_model`` (or a real model in
    tests). ``rows`` is an iterable of unsaved instances. ``key_fields`` names
    the attributes whose tuple identifies "this row is already represented" —
    usually a single FK like ``('tracked_opportunity_id',)`` for backfills that
    should run once per parent record. Returns the number of rows created.
    """
    rows = list(rows)
    if not rows:
        return 0

    existing = set(model.objects.values_list(*key_fields))

    def _key(row):
        return tuple(getattr(row, f) for f in key_fields)

    to_create = [r for r in rows if _key(r) not in existing]
    if to_create:
        model.objects.bulk_create(to_create)
    return len(to_create)
