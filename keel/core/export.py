"""CSV export utilities shared across DockLabs products.

Usage:
    class AwardListView(CSVExportMixin, ListView):
        model = Award
        csv_filename = 'awards.csv'
        csv_columns = [
            ('Award Number', 'award_number'),
            ('Title', 'title'),
            ('Status', 'get_status_display'),
            ('Agency', 'agency.name'),
            ('Amount', lambda obj: f'${obj.award_amount:,.2f}'),
        ]

    Visiting ?export=csv on the list view URL will download the CSV.
"""
import csv

from django.http import HttpResponse


class CSVExportMixin:
    """Add CSV export to any ListView via ``?export=csv``.

    Attributes:
        csv_filename: Name of the downloaded file.
        csv_columns: List of (header, field_or_callable) tuples.
            - String fields support dotted paths (e.g., ``'agency.name'``).
            - Callable attributes on the object are auto-invoked
              (e.g., ``'get_status_display'``).
            - Lambdas/functions receive the object as the sole argument.
    """

    csv_filename = 'export.csv'
    csv_columns = []

    def get(self, request, *args, **kwargs):
        if request.GET.get('export') == 'csv':
            return self.export_csv()
        return super().get(request, *args, **kwargs)

    def export_csv(self):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{self.csv_filename}"'

        writer = csv.writer(response)
        writer.writerow([col[0] for col in self.csv_columns])

        queryset = self.get_queryset()
        for obj in queryset:
            row = []
            for _, field in self.csv_columns:
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
