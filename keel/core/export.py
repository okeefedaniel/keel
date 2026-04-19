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


# Characters that Excel / LibreOffice / Google Sheets interpret as the start of
# a formula. Prefixing with a single quote neutralizes the cell.
_CSV_FORMULA_CHARS = ('=', '+', '-', '@', '\t', '\r')


def csv_safe(value):
    """Neutralize CSV formula-injection payloads before writing to a spreadsheet.

    Strings that begin with =, +, -, @, tab, or CR can be interpreted as
    formulas by Excel and trigger remote content / RCE when a staff user
    opens the exported file. Prefix with a single quote so the cell renders
    as literal text. Non-string values pass through unchanged.
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in _CSV_FORMULA_CHARS:
        return "'" + value
    return value


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
            writer.writerow([csv_safe(v) for v in row])

        return response
