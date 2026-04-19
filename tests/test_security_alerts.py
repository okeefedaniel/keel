"""Tests for ``keel.security.alerts.check_failed_logins``.

Pins the filter to ``action='login_failed'``. Prior code filtered
``action='login'`` — a value the AuditLog never emits for failures —
so the excessive-login alert could literally never fire.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone

from keel.security.alerts import check_failed_logins


class _FakeManager:
    """In-memory AuditLog substitute that records filter calls."""

    def __init__(self, rows):
        self._rows = rows
        self.last_filter_kwargs = None

    def filter(self, **kwargs):
        self.last_filter_kwargs = kwargs
        matching = [
            r for r in self._rows
            if r['action'] == kwargs.get('action')
            and r['timestamp'] >= kwargs.get('timestamp__gte')
        ]
        return _FakeQuerySet(matching)


class _FakeQuerySet:
    def __init__(self, rows):
        self._rows = rows

    def values(self, *fields):
        self._group = fields
        return self

    def annotate(self, **kwargs):
        # Simulate annotate(count=Count('id'))
        buckets = {}
        for r in self._rows:
            key = tuple(r.get(f) for f in self._group)
            buckets.setdefault(key, []).append(r)
        self._annotated = [
            {**{f: k[i] for i, f in enumerate(self._group)}, 'count': len(rs)}
            for k, rs in buckets.items()
        ]
        return self

    def filter(self, **kwargs):
        threshold = kwargs.get('count__gte', 0)
        return [x for x in self._annotated if x['count'] >= threshold]


class _FakeModel:
    objects = None  # set per test


def test_check_failed_logins_uses_login_failed_action():
    now = timezone.now()
    _FakeModel.objects = _FakeManager([
        {'action': 'login_failed', 'ip_address': '1.1.1.1', 'timestamp': now},
        {'action': 'login_failed', 'ip_address': '1.1.1.1', 'timestamp': now},
        {'action': 'login_failed', 'ip_address': '1.1.1.1', 'timestamp': now},
        {'action': 'login', 'ip_address': '1.1.1.1', 'timestamp': now},
    ])
    alerts = check_failed_logins(_FakeModel, window_minutes=15, threshold=2)
    assert _FakeModel.objects.last_filter_kwargs['action'] == 'login_failed'
    assert len(alerts) == 1
    assert alerts[0].details['ip'] == '1.1.1.1'
    assert alerts[0].details['count'] == 3


def test_check_failed_logins_below_threshold():
    now = timezone.now()
    _FakeModel.objects = _FakeManager([
        {'action': 'login_failed', 'ip_address': '2.2.2.2', 'timestamp': now},
    ])
    alerts = check_failed_logins(_FakeModel, window_minutes=15, threshold=5)
    assert alerts == []
