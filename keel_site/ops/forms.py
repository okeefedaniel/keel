"""Filter form for /ops/.

Three filters: product (multi-select), status (one of any/ok/warn/failed/errored),
and window (last 1h, 24h, 7d, 30d). Free-text `q` for verb / summary search.

Kept deliberately smaller than the audit form — /ops/ is glanceable; complex
faceting belongs on /audit/ which is the FOIA/IR investigation surface.
"""
from __future__ import annotations

from datetime import timedelta

from django import forms
from django.utils import timezone

WINDOW_CHOICES = [
    ('1h', 'Last hour'),
    ('24h', 'Last 24 hours'),
    ('7d', 'Last 7 days'),
    ('30d', 'Last 30 days'),
]
WINDOW_DURATIONS = {
    '1h': timedelta(hours=1),
    '24h': timedelta(hours=24),
    '7d': timedelta(days=7),
    '30d': timedelta(days=30),
}

STATUS_CHOICES = [
    ('any', 'All statuses'),
    ('failed', 'Failed only'),
    ('errored', 'Errored only'),
    ('warn', 'Warnings only'),
    ('ok', 'OK only'),
]


class OpsFilterForm(forms.Form):
    products = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES, required=False, initial='any',
    )
    window = forms.ChoiceField(
        choices=WINDOW_CHOICES, required=False, initial='24h',
    )
    q = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, visible_products: list[str], **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['products'].choices = [(p, p) for p in visible_products]

    def cleaned_window(self) -> tuple:
        """Returns (window_start, window_end) datetimes from the choice."""
        window = self.cleaned_data.get('window') or '24h'
        delta = WINDOW_DURATIONS.get(window, WINDOW_DURATIONS['24h'])
        now = timezone.now()
        return (now - delta, now)
