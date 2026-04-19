"""FOIA Export — one-click audit log + activity export to Admiralty.

**DEPRECATED (2026-04-19):** this module is the audit-log, time-range
variant of FOIA export. It predates ``keel.foia.export`` which is the
canonical registry-based pipeline referenced by ``keel/CLAUDE.md``.

Going forward:

* New products should register exportable types with
  ``keel.foia.export.foia_export_registry`` and include
  ``keel.foia.urls`` (not ``keel.core.foia_urls``).
* The audit-log bulk-export view below remains available as an admin
  convenience until all products have migrated their FOIA buttons to the
  registry. When the last caller is gone, delete this module AND
  ``keel.core.foia_urls`` in the same commit.

Current callers (verified 2026-04-19): admiralty, beacon, harbor,
manifest all ``include('keel.core.foia_urls')`` in their root URLConf;
none of them use the registry yet, so the audit-log path is still the
only working export on three of them. Do not delete until that changes.

Legacy usage in product urls.py:
    from keel.core.foia_export import foia_export_view
    path('foia-export/', foia_export_view, name='foia_export'),

Or include the keel.core.foia_urls:
    path('keel/', include('keel.core.foia_urls')),
"""
import csv
import io
import json
import logging
from datetime import datetime

from django.apps import apps

from keel.core.export import csv_safe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _get_audit_model():
    """Resolve the product's AuditLog model."""
    model_path = getattr(settings, 'KEEL_AUDIT_LOG_MODEL', 'core.AuditLog')
    return apps.get_model(model_path)


def _admin_check(user):
    if user.is_superuser:
        return True
    try:
        from keel.accounts.models import ProductAccess
        return ProductAccess.objects.filter(
            user=user, role__in=('admin', 'system_admin'), is_active=True,
        ).exists()
    except Exception:
        return getattr(user, 'role', None) in ('admin', 'system_admin')


def _serialize_audit_entry(entry):
    """Convert an AuditLog entry to a dict suitable for export."""
    return {
        'id': str(entry.pk),
        'timestamp': entry.timestamp.isoformat(),
        'user': str(entry.user) if entry.user else 'System',
        'user_email': getattr(entry.user, 'email', '') if entry.user else '',
        'action': entry.action,
        'action_display': entry.get_action_display(),
        'entity_type': entry.entity_type,
        'entity_id': str(entry.entity_id),
        'description': entry.description,
        'changes': entry.changes or {},
        'ip_address': entry.ip_address or '',
    }


@login_required
@require_http_methods(['GET', 'POST'])
def foia_export_view(request):
    """Export audit logs for a date range.

    GET: Show date range picker form.
    POST: Generate and download the export package.
    """
    from django.core.exceptions import PermissionDenied
    if not _admin_check(request.user):
        raise PermissionDenied

    product_name = getattr(settings, 'KEEL_PRODUCT_NAME', 'unknown')

    if request.method == 'GET':
        return render(request, 'core/foia_export.html', {
            'product_name': product_name,
        })

    # POST — generate export
    date_from = request.POST.get('date_from', '').strip()
    date_to = request.POST.get('date_to', '').strip()
    export_format = request.POST.get('format', 'json')

    if not date_from or not date_to:
        return render(request, 'core/foia_export.html', {
            'product_name': product_name,
            'error': 'Both start and end dates are required.',
        })

    try:
        start = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
        end = timezone.make_aware(
            datetime.strptime(date_to, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59,
            )
        )
    except ValueError:
        return render(request, 'core/foia_export.html', {
            'product_name': product_name,
            'error': 'Invalid date format. Use YYYY-MM-DD.',
        })

    AuditLog = _get_audit_model()
    entries = AuditLog.objects.filter(
        timestamp__gte=start,
        timestamp__lte=end,
    ).select_related('user').order_by('timestamp')

    count = entries.count()

    # Log the export itself
    from keel.core.audit import log_audit
    log_audit(
        user=request.user,
        action='export',
        entity_type='FOIAExport',
        entity_id=f'{product_name}_{date_from}_{date_to}',
        description=(
            f'FOIA export: {count} audit records from {date_from} to {date_to} '
            f'for {product_name}'
        ),
        ip_address=getattr(request, 'audit_ip', None),
    )

    if export_format == 'csv':
        return _export_csv(entries, product_name, date_from, date_to)
    else:
        return _export_json(entries, product_name, date_from, date_to, count)


def _export_json(entries, product_name, date_from, date_to, count):
    """Export as structured JSON package for Admiralty ingestion."""
    package = {
        'export_metadata': {
            'product': product_name,
            'date_range': {'from': date_from, 'to': date_to},
            'record_count': count,
            'exported_at': timezone.now().isoformat(),
            'format_version': '1.0',
        },
        'audit_records': [_serialize_audit_entry(e) for e in entries],
    }

    # Collect unique entity types and IDs for a summary
    entity_summary = {}
    for entry in entries:
        key = entry.entity_type
        if key not in entity_summary:
            entity_summary[key] = set()
        entity_summary[key].add(str(entry.entity_id))

    package['entity_summary'] = {
        k: {'count': len(v), 'ids': sorted(v)}
        for k, v in sorted(entity_summary.items())
    }

    response = HttpResponse(
        json.dumps(package, indent=2, default=str),
        content_type='application/json',
    )
    filename = f'foia_export_{product_name}_{date_from}_{date_to}.json'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _export_csv(entries, product_name, date_from, date_to):
    """Export as CSV for simpler consumption."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Timestamp', 'User', 'User Email', 'Action', 'Entity Type',
        'Entity ID', 'Description', 'Changes', 'IP Address',
    ])

    for entry in entries:
        data = _serialize_audit_entry(entry)
        writer.writerow([csv_safe(v) for v in (
            data['timestamp'],
            data['user'],
            data['user_email'],
            data['action_display'],
            data['entity_type'],
            data['entity_id'],
            data['description'],
            json.dumps(data['changes']) if data['changes'] else '',
            data['ip_address'],
        )])

    response = HttpResponse(output.getvalue(), content_type='text/csv')
    filename = f'foia_export_{product_name}_{date_from}_{date_to}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
