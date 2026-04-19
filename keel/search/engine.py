"""PostgreSQL FTS search engine — subclass per product.

Provides three-tier search:
1. Instant typeahead (<30ms) with prefix, FTS, and trigram fallback
2. Full ranked search with snippets
3. Extensible filter system

Usage:
    class GrantSearchEngine(SearchEngine):
        model = FederalOpportunity
        search_fields = {'title': 'A', 'agency_name': 'B', 'description': 'C'}
        instant_display_fields = ['title', 'agency_name', 'opportunity_status']
        trigram_fields = ['title']

        def format_instant_result(self, row):
            return {'id': row['id'], 'title': row['title'], ...}
"""
import logging

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import connection
from django.db.models import F, Q

logger = logging.getLogger(__name__)


class SearchEngine:
    """PostgreSQL FTS search engine base class.

    Subclass and set:
        model — Django model with a SearchVectorField
        search_fields — dict of {field_name: weight} for vector construction
        trigram_fields — list of fields with GIN trigram indexes
    """

    model = None
    search_vector_field = 'search_vector'
    search_fields = {}          # {'title': 'A', 'description': 'C'}
    trigram_fields = ['title']  # fields with pg_trgm GIN indexes
    instant_display_fields = [] # fields to SELECT in instant search
    default_limit = 50
    instant_limit = 15

    # -----------------------------------------------------------------------
    # Full ranked search
    # -----------------------------------------------------------------------

    def search(self, query, filters=None, limit=None):
        """Run a ranked full-text search. Returns annotated queryset."""
        if not query or not query.strip():
            return self.model.objects.none()

        limit = limit or self.default_limit
        search_query = self._build_search_query(query)

        qs = self.model.objects.annotate(
            rank=SearchRank(F(self.search_vector_field), search_query),
        ).filter(**{self.search_vector_field: search_query})

        if filters:
            filter_kwargs = self.get_filter_kwargs(filters)
            if filter_kwargs:
                qs = qs.filter(**filter_kwargs)

        return qs.order_by('-rank')[:limit]

    def get_filter_kwargs(self, filters):
        """Convert a filter dict to Django queryset kwargs. Override per product."""
        return {k: v for k, v in (filters or {}).items() if v}

    # -----------------------------------------------------------------------
    # Instant typeahead search (3 strategies)
    # -----------------------------------------------------------------------

    def instant_search(self, query, filters=None, limit=None):
        """Fast typeahead — prefix → FTS → trigram fallback.

        Returns list of dicts formatted by format_instant_result().
        """
        if not query or len(query.strip()) < 2:
            return []

        q = query.strip()
        limit = limit or self.instant_limit

        # Build filter clause for raw SQL
        filter_clause, filter_params = self._build_filter_sql(filters)

        # Strategy 1: Product-specific prefix match
        results = self.get_prefix_match(q, filter_clause, filter_params, limit)
        if results is not None:
            return results

        # Strategy 2: FTS on search_vector (GIN indexed)
        results = self._fts_instant(q, filter_clause, filter_params, limit)
        if results:
            return results

        # Strategy 3: Trigram similarity fallback (catches typos)
        return self._trigram_instant(q, filter_clause, filter_params, limit)

    def get_prefix_match(self, query, filter_clause, filter_params, limit):
        """Override for domain-specific prefix matching (e.g., bill numbers).

        Return list of result dicts, or None to skip this strategy.
        """
        return None

    def format_instant_result(self, row):
        """Format a raw SQL row dict for the typeahead dropdown.

        Override to customize per product.
        """
        return row

    # -----------------------------------------------------------------------
    # Internal search strategies
    # -----------------------------------------------------------------------

    def _fts_instant(self, query, filter_clause, filter_params, limit):
        """Strategy 2: Full-text search on search_vector."""
        words = query.split()
        if len(words) == 1:
            tsquery = f"{words[0]}:*"
        else:
            parts = words[:-1] + [f"{words[-1]}:*"]
            tsquery = " & ".join(parts)

        table = self.model._meta.db_table
        sv_field = self.search_vector_field
        select_cols = self._instant_select_cols()

        sql = f"""
            SELECT {select_cols},
                   ts_rank({sv_field}, to_tsquery('english', %s)) AS rank
            FROM {table}
            WHERE {sv_field} @@ to_tsquery('english', %s)
            {filter_clause}
            ORDER BY rank DESC
            LIMIT %s
        """
        params = [tsquery, tsquery] + filter_params + [limit]
        return self._execute_instant(sql, params)

    def _trigram_instant(self, query, filter_clause, filter_params, limit):
        """Strategy 3: Trigram similarity fallback for typos."""
        if not self.trigram_fields:
            return []

        trgm_field = self.trigram_fields[0]
        table = self.model._meta.db_table
        select_cols = self._instant_select_cols()

        sql = f"""
            SELECT {select_cols}
            FROM {table}
            WHERE {trgm_field} %% %s
            {filter_clause}
            ORDER BY similarity({trgm_field}, %s) DESC
            LIMIT %s
        """
        params = [query, query] + filter_params + [limit]
        return self._execute_instant(sql, params)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _build_search_query(self, raw_query):
        """Convert user input to a SearchQuery."""
        raw = raw_query.strip()
        if raw.startswith('"') and raw.endswith('"'):
            return SearchQuery(raw.strip('"'), search_type='phrase')
        return SearchQuery(raw, search_type='websearch')

    def _allowed_column_names(self):
        """Return the set of column names that are safe to interpolate.

        Derived from the model's own field list. A subclass that passes
        an arbitrary attacker-controlled string into a filter kwarg (for
        example by forwarding raw request.GET keys) cannot escape this
        allowlist — unknown columns are rejected before reaching SQL.
        """
        try:
            return {
                f.column
                for f in self.model._meta.get_fields()
                if hasattr(f, 'column') and f.column
            }
        except Exception:
            return set()

    def _build_filter_sql(self, filters):
        """Convert filter dict to SQL WHERE clauses.

        Override for complex filter logic. Returns (clause_str, params_list).
        Field names are allowlisted against the model's own columns so a
        subclass that forwards untrusted keys cannot inject SQL.
        """
        if not filters:
            return '', []

        allowed = self._allowed_column_names()
        clauses = []
        params = []
        filter_kwargs = self.get_filter_kwargs(filters)
        for field, value in filter_kwargs.items():
            if field not in allowed:
                logger.warning(
                    "search: dropping filter with disallowed field %r (not a %s column)",
                    field, self.model.__name__ if self.model else '?',
                )
                continue
            clauses.append(f'AND "{field}" = %s')
            params.append(value)
        return ' '.join(clauses), params

    def _instant_select_cols(self):
        """Build SELECT column list for instant search.

        Columns are validated against the model's own field list so a
        misconfigured subclass cannot interpolate arbitrary SQL into the
        SELECT clause.
        """
        allowed = self._allowed_column_names()
        requested = ['id']
        if self.instant_display_fields:
            requested.extend(self.instant_display_fields)
        else:
            requested.extend(self.search_fields.keys())
        safe = [c for c in requested if c in allowed or c == 'id']
        dropped = [c for c in requested if c not in safe]
        if dropped:
            logger.warning(
                "search: dropping unknown instant_display columns %r on %s",
                dropped, self.model.__name__ if self.model else '?',
            )
        return ', '.join(f'"{c}"' for c in safe)

    def _execute_instant(self, sql, params):
        """Execute instant search SQL and format results."""
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return [self.format_instant_result(row) for row in rows]

    # -----------------------------------------------------------------------
    # Search vector maintenance
    # -----------------------------------------------------------------------

    def update_search_vectors(self, queryset=None):
        """Bulk-update search vectors using raw SQL for speed.

        Call after data sync or as a management command.
        """
        if not self.search_fields:
            return 0

        table = self.model._meta.db_table
        allowed = self._allowed_column_names()
        if self.search_vector_field not in allowed:
            raise ValueError(
                f"search_vector_field={self.search_vector_field!r} is not a "
                f"column on {self.model.__name__}"
            )
        sv_field = f'"{self.search_vector_field}"'

        # Build weighted tsvector expression. Validate every column name
        # against the model's own fields; refuse to interpolate anything
        # else so a bad subclass definition can't produce injectable SQL.
        _ALLOWED_WEIGHTS = {'A', 'B', 'C', 'D'}
        parts = []
        for field, weight in self.search_fields.items():
            if field not in allowed:
                raise ValueError(
                    f"search_fields contains unknown column {field!r} for {self.model.__name__}"
                )
            if weight not in _ALLOWED_WEIGHTS:
                raise ValueError(
                    f"search_fields[{field!r}] weight must be one of {_ALLOWED_WEIGHTS}, got {weight!r}"
                )
            parts.append(
                f"setweight(to_tsvector('english', coalesce(\"{field}\", '')), '{weight}')"
            )
        vector_expr = ' || '.join(parts)

        if queryset is not None:
            # Update specific records
            ids = list(queryset.values_list('pk', flat=True))
            if not ids:
                return 0
            placeholders = ','.join(['%s'] * len(ids))
            sql = f"""
                UPDATE {table}
                SET {sv_field} = {vector_expr}
                WHERE id IN ({placeholders})
            """
            with connection.cursor() as cursor:
                cursor.execute(sql, ids)
                return cursor.rowcount
        else:
            # Update all records
            sql = f"UPDATE {table} SET {sv_field} = {vector_expr}"
            with connection.cursor() as cursor:
                cursor.execute(sql)
                return cursor.rowcount
