"""Tests for ``keel.search.SearchEngine`` column-name safety.

The engine previously f-string-interpolated caller-supplied column names
into raw SQL. These tests pin the allowlist behaviour so a subclass that
forwards unvalidated request.GET keys cannot produce injectable SQL.
"""
import pytest

from keel.search.engine import SearchEngine


class _FakeField:
    def __init__(self, column):
        self.column = column


class _FakeMeta:
    db_table = 'fake_table'

    def get_fields(self):
        return [_FakeField('id'), _FakeField('title'), _FakeField('status')]


class _FakeModel:
    _meta = _FakeMeta()
    __name__ = 'FakeModel'


class _FakeEngine(SearchEngine):
    model = _FakeModel
    search_fields = {'title': 'A'}
    instant_display_fields = ['title', 'status']


def test_build_filter_sql_drops_unknown_columns():
    eng = _FakeEngine()
    eng.get_filter_kwargs = lambda filters: filters  # forward raw dict
    clause, params = eng._build_filter_sql({'status': 'open', 'evil; DROP TABLE users; --': 'x'})
    assert 'DROP TABLE' not in clause
    assert 'evil' not in clause
    assert '"status"' in clause
    assert params == ['open']


def test_build_filter_sql_quotes_identifier():
    eng = _FakeEngine()
    eng.get_filter_kwargs = lambda filters: filters
    clause, _ = eng._build_filter_sql({'title': 'hi'})
    assert '"title"' in clause


def test_instant_select_cols_filters_unknown():
    eng = _FakeEngine()
    eng.instant_display_fields = ['title', 'status', 'not_a_column']
    sql = eng._instant_select_cols()
    assert '"title"' in sql
    assert '"status"' in sql
    assert 'not_a_column' not in sql


def test_empty_filters_returns_empty_clause():
    eng = _FakeEngine()
    clause, params = eng._build_filter_sql({})
    assert clause == ''
    assert params == []
