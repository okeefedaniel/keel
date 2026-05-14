"""Filter form for /audit/."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django import forms
from django.utils import timezone

from keel.accounts.models import AuditLog

_WINDOW_CHOICES = [
    ('1h', 'Last hour'),
    ('24h', 'Last 24 hours'),
    ('7d', 'Last 7 days'),
    ('30d', 'Last 30 days'),
    ('custom', 'Custom range'),
]

_WINDOW_TO_DELTA = {
    '1h': timedelta(hours=1),
    '24h': timedelta(hours=24),
    '7d': timedelta(days=7),
    '30d': timedelta(days=30),
}

MAX_WINDOW = timedelta(days=365)


class AuditFilterForm(forms.Form):
    window = forms.ChoiceField(
        choices=_WINDOW_CHOICES, required=False, initial='24h',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    window_from = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control form-control-sm', 'type': 'datetime-local',
        }),
    )
    window_to = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control form-control-sm', 'type': 'datetime-local',
        }),
    )
    products = forms.MultipleChoiceField(
        required=False, choices=[],
        widget=forms.SelectMultiple(attrs={'class': 'form-select form-select-sm'}),
    )
    actions = forms.MultipleChoiceField(
        required=False,
        choices=AuditLog.Action.choices,
        widget=forms.SelectMultiple(attrs={'class': 'form-select form-select-sm'}),
    )
    q = forms.CharField(
        required=False, max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Keyword (description, entity, user)',
        }),
    )

    def __init__(self, *args, visible_products: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        codes = visible_products or []
        self.fields['products'].choices = [(c, c.title()) for c in codes]

    def cleaned_window(self) -> tuple[datetime, datetime]:
        """Return (window_start, window_end) as tz-aware UTC datetimes.

        Falls back to the last-24h preset if nothing is set or the form
        is invalid.
        """
        window = self.cleaned_data.get('window') or '24h'
        end = timezone.now()
        if window == 'custom':
            start = self.cleaned_data.get('window_from')
            stop = self.cleaned_data.get('window_to')
            if start is None:
                start = end - _WINDOW_TO_DELTA['24h']
            if stop is None:
                stop = end
            start = _ensure_utc(start)
            stop = _ensure_utc(stop)
            if stop - start > MAX_WINDOW:
                start = stop - MAX_WINDOW
            return start, stop
        delta = _WINDOW_TO_DELTA.get(window, _WINDOW_TO_DELTA['24h'])
        return end - delta, end

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('window') == 'custom':
            wf = cleaned.get('window_from')
            wt = cleaned.get('window_to')
            if wf and wt and wf > wt:
                raise forms.ValidationError('"from" must be before "to".')
            if wf and wt and (wt - wf) > MAX_WINDOW:
                raise forms.ValidationError('Window cannot exceed 365 days.')
        return cleaned


def _ensure_utc(dt: datetime) -> datetime:
    """Stamp tzinfo=UTC on naive datetimes (review decision A8)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=dt_timezone.utc)
    return dt
