"""Reusable view mixins shared across DockLabs products."""
import csv
import logging
from urllib.parse import quote

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count
from django.db.models.expressions import BaseExpression
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


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


class BulkActionMixin:
    """Add bulk-action support to a ListView.

    Handles the pattern: select IDs → validate → execute → audit.

    Subclasses define ``bulk_actions`` as a dict mapping action names to
    handler methods.

    Usage:
        class ApplicationListView(BulkActionMixin, ListView):
            model = Application
            bulk_actions = {
                'approve': 'bulk_approve',
                'export_csv': 'bulk_export_csv',
            }
            bulk_id_param = 'ids'  # POST param with comma-separated IDs

            def bulk_approve(self, queryset):
                count = queryset.update(status='approved')
                return self.bulk_success(f'{count} applications approved.')

            def bulk_export_csv(self, queryset):
                return self.bulk_csv_response(
                    queryset, 'applications.csv',
                    [('ID', 'pk'), ('Title', 'title'), ('Status', 'get_status_display')],
                )
    """

    bulk_actions = {}
    bulk_id_param = 'ids'

    def post(self, request, *args, **kwargs):
        action = request.POST.get('bulk_action', '')
        handler_name = self.bulk_actions.get(action)
        if not handler_name:
            return JsonResponse({'error': f'Unknown action: {action}'}, status=400)

        handler = getattr(self, handler_name, None)
        if not handler:
            return JsonResponse({'error': f'Handler not found: {handler_name}'}, status=500)

        ids_raw = request.POST.get(self.bulk_id_param, '')
        ids = [i.strip() for i in ids_raw.split(',') if i.strip()]
        if not ids:
            return JsonResponse({'error': 'No items selected.'}, status=400)

        queryset = self.get_queryset().filter(pk__in=ids)
        return handler(queryset)

    def bulk_success(self, message, redirect_url=None):
        """Return a success response (JSON for htmx, redirect otherwise)."""
        from django.contrib import messages
        from django.shortcuts import redirect as redir

        if self.request.headers.get('HX-Request'):
            return JsonResponse({'message': message})
        messages.success(self.request, message)
        return redir(redirect_url or self.request.get_full_path())

    def bulk_csv_response(self, queryset, filename, columns):
        """Generate a CSV download from a queryset.

        Args:
            queryset: Filtered queryset of selected objects.
            filename: Download filename.
            columns: List of (header, field_or_callable) tuples,
                same format as CSVExportMixin.csv_columns.
        """
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([col[0] for col in columns])

        for obj in queryset:
            row = []
            for _, field in columns:
                if callable(field):
                    row.append(field(obj))
                else:
                    value = obj
                    for attr in field.split('.'):
                        value = getattr(value, attr, '') if value else ''
                    if callable(value):
                        value = value()
                    row.append(value)
            writer.writerow(row)

        return response


class WorkQueueMixin:
    """Add work-queue context to a dashboard TemplateView.

    Provides status counts, unassigned (claimable) items, and per-user
    assignment tracking for any model with ``status`` and ``assigned_to``
    fields.

    Usage:
        class DashboardView(WorkQueueMixin, LoginRequiredMixin, TemplateView):
            work_queue_model = Invitation
            terminal_statuses = ('completed', 'declined', 'cancelled')
            assigned_to_field = 'assigned_to'  # default

    Adds to context: status_counts, total_count, unassigned_count,
    my_assignment_count, my_assignments.
    """

    work_queue_model = None
    terminal_statuses = ()
    assigned_to_field = 'assigned_to'

    def get_work_queue_queryset(self):
        return self.work_queue_model.objects.all()

    def get_work_queue_context(self):
        qs = self.get_work_queue_queryset()
        user = self.request.user
        ctx = {}

        # Status counts
        counts = qs.values('status').annotate(count=Count('id'))
        status_counts = {row['status']: row['count'] for row in counts}
        ctx['status_counts'] = status_counts
        ctx['total_count'] = sum(status_counts.values())

        # Unassigned (claimable)
        ctx['unassigned_count'] = qs.filter(
            **{f'{self.assigned_to_field}__isnull': True},
        ).exclude(status__in=self.terminal_statuses).count()

        # My assignments
        my_qs = qs.filter(
            **{self.assigned_to_field: user},
        ).exclude(status__in=self.terminal_statuses)
        ctx['my_assignment_count'] = my_qs.count()
        ctx['my_assignments'] = my_qs.order_by('-created_at')[:10]

        return ctx

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.work_queue_model:
            ctx.update(self.get_work_queue_context())
        return ctx
