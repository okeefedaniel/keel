"""Reusable view mixins shared across DockLabs products."""
from urllib.parse import quote

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models.expressions import BaseExpression


class AgencyStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict view to agency staff."""

    def test_func(self):
        return self.request.user.is_agency_staff


class AgencyObjectMixin:
    """Filter querysets by the user's agency for non-system-admins.

    Usage:
        class MyListView(AgencyObjectMixin, ListView):
            model = MyModel
            # Defaults to filtering on 'agency' field
            # Override get_agency_field() to change
    """

    def get_agency_field(self):
        return 'agency'

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role != 'system_admin' and user.agency_id:
            qs = qs.filter(**{self.get_agency_field(): user.agency})
        return qs


class SortableListMixin:
    """Add server-side column sorting to any ListView.

    Define ``sortable_fields`` as a dict mapping URL param names to either:
    - A string model field path for .order_by()
    - A Django ORM expression for non-trivial ordering

    Usage:
        class CompanyListView(SortableListMixin, ListView):
            model = Company
            sortable_fields = {
                'name': 'name',
                'created': 'created_at',
                'interactions': Count('interactions'),
            }
            default_sort = 'name'
    """

    sortable_fields = {}
    default_sort = ''
    default_dir = 'asc'

    def get_sort_params(self):
        sort = self.request.GET.get('sort', self.default_sort)
        direction = self.request.GET.get('dir', self.default_dir)
        if sort not in self.sortable_fields:
            sort = self.default_sort
        if direction not in ('asc', 'desc'):
            direction = self.default_dir
        return sort, direction

    def apply_sorting(self, qs):
        sort, direction = self.get_sort_params()
        if not sort:
            return qs
        field = self.sortable_fields[sort]
        if isinstance(field, BaseExpression):
            alias = f'_sort_{sort}'
            qs = qs.annotate(**{alias: field})
            order_field = alias
        else:
            order_field = field
        if direction == 'desc':
            order_field = f'-{order_field}'
        return qs.order_by(order_field)

    def get_queryset(self):
        return self.apply_sorting(super().get_queryset())

    def _build_params(self, exclude):
        parts = []
        for key in self.request.GET:
            if key not in exclude:
                for val in self.request.GET.getlist(key):
                    parts.append(f'{quote(key)}={quote(val)}')
        return '&'.join(parts)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sort, direction = self.get_sort_params()
        ctx['current_sort'] = sort
        ctx['current_dir'] = direction
        ctx['filter_params'] = self._build_params({'sort', 'dir', 'page'})
        ctx['pagination_params'] = self._build_params({'page'})
        return ctx
