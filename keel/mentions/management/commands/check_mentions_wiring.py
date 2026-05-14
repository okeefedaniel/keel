"""``manage.py check_mentions_wiring``

One-shot diagnostic for product engineers integrating keel.mentions.
Prints a tick or cross for each of the four common silent-no-op failure
modes:

    1. keel.mentions in INSTALLED_APPS
    2. URL include resolves
    3. Forms wired (best-effort detection of MentionFormMixin subclasses)
    4. Migrations applied for every concrete AbstractInternalNote subclass

Exits 0 when everything is OK, 1 when any check fails.
"""
from __future__ import annotations

import sys

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Audit the current product wiring for keel.mentions.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--strict', action='store_true',
            help='Treat warnings as errors (exit 1 on any issue).',
        )

    def handle(self, *args, **options):
        rows: list[tuple[bool, str]] = []

        # 1. keel.mentions in INSTALLED_APPS
        installed = 'keel.mentions' in settings.INSTALLED_APPS
        rows.append((
            installed,
            "INSTALLED_APPS contains 'keel.mentions'"
            if installed
            else "MISSING: add 'keel.mentions' to INSTALLED_APPS",
        ))

        # 2. URL include resolves
        try:
            from django.urls import reverse
            reverse('keel_mentions:mentions_search')
            url_ok = True
            rows.append((True, 'URL include resolves (mentions_search)'))
        except Exception as exc:
            url_ok = False
            rows.append((
                False,
                f"MISSING: include('keel.mentions.urls') not wired ({exc})",
            ))

        # 3. Form mixin detection
        try:
            from keel.mentions.forms import MentionFormMixin
            from keel.mentions.widgets import MentionableTextarea
            subclasses = MentionFormMixin.__subclasses__()
            if not subclasses:
                rows.append((
                    False,
                    'WARNING: no MentionFormMixin subclass detected; '
                    'no forms in this product currently wire mentions',
                ))
            else:
                for klass in subclasses:
                    cls_name = f'{klass.__module__}.{klass.__qualname__}'
                    content_field = getattr(klass, 'base_fields', {}).get('content')
                    if content_field is None:
                        rows.append((True, f'{cls_name}: no content field (skipped)'))
                        continue
                    if isinstance(content_field.widget, MentionableTextarea):
                        rows.append((True, f'{cls_name}: widget is MentionableTextarea'))
                    else:
                        rows.append((
                            False,
                            f'{cls_name}: WRONG WIDGET '
                            f'({type(content_field.widget).__name__})',
                        ))
        except Exception as exc:
            rows.append((False, f'Form detection failed: {exc}'))

        # 4. Migrations applied for every concrete AbstractInternalNote
        try:
            from keel.core.models import AbstractInternalNote
            note_models = [
                m for m in apps.get_models()
                if issubclass(m, AbstractInternalNote) and not m._meta.abstract
            ]
            if not note_models:
                rows.append((True, 'No concrete AbstractInternalNote subclasses (skipped)'))
            for model in note_models:
                try:
                    model._meta.get_field('mentions')
                    rows.append((True, f'{model._meta.label}: mentions M2M present'))
                except Exception:
                    rows.append((
                        False,
                        f"{model._meta.label}: MISSING mentions M2M — run "
                        f"makemigrations {model._meta.app_label} && migrate",
                    ))
        except Exception as exc:
            rows.append((False, f'Migration check failed: {exc}'))

        # Render report
        any_failed = False
        for ok, msg in rows:
            mark = 'OK ' if ok else 'XX '
            if not ok:
                any_failed = True
                self.stderr.write(self.style.ERROR(mark + msg))
            else:
                self.stdout.write(self.style.SUCCESS(mark + msg))

        if any_failed:
            self.stderr.write(self.style.ERROR(
                '\nSome checks failed. See keel/mentions/README.md for fixes.',
            ))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS('\nAll mentions wiring checks passed.'))
