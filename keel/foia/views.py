"""FOIA Export views — shared endpoint for exporting records to FOIA queue."""
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .export import foia_export_registry, submit_to_foia

logger = logging.getLogger(__name__)

# Roles allowed to export records to FOIA
FOIA_EXPORT_ROLES = {
    'foia_attorney', 'foia_officer', 'foia_manager',
    'agency_admin', 'system_admin', 'admin',
}


def _has_foia_role(user):
    """Check if user has a role that permits FOIA export."""
    if user.is_superuser:
        return True
    role = getattr(user, 'role', None)
    if role and role in FOIA_EXPORT_ROLES:
        return True
    # Check via ProductAccess if available
    if hasattr(user, 'product_access'):
        return user.product_access.filter(
            role__in=FOIA_EXPORT_ROLES, is_active=True,
        ).exists()
    return False


@staff_member_required
@require_POST
def export_to_foia(request):
    """Universal endpoint for exporting any record to FOIA queue.

    POST params:
        product: source product name
        record_type: type of record (e.g., 'testimony', 'interaction')
        record_id: PK of the record in the source product
        foia_request_id: (optional) FK to a specific FOIA request
    """
    if not _has_foia_role(request.user):
        return JsonResponse({'error': 'Insufficient permissions'}, status=403)

    product = request.POST.get('product', '').strip()
    record_type = request.POST.get('record_type', '').strip()
    record_id = request.POST.get('record_id', '').strip()
    foia_request_id = request.POST.get('foia_request_id', '').strip()

    if not all([product, record_type, record_id]):
        return JsonResponse(
            {'error': 'product, record_type, and record_id are required'},
            status=400,
        )

    # Try to use the registry first (structured export)
    entry = foia_export_registry.get_type(product, record_type)
    if entry:
        try:
            export_record = foia_export_registry.export_record(
                product, record_type, record_id,
            )
            item = submit_to_foia(
                source_product=export_record.source_product,
                record_type=export_record.record_type,
                record_id=export_record.record_id,
                title=export_record.title,
                content=export_record.content,
                created_by=export_record.created_by,
                created_at=export_record.created_at,
                metadata=export_record.metadata,
                submitted_by=request.user,
                foia_request_id=foia_request_id,
            )
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
    else:
        # Fallback: accept raw title/content from the POST
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()
        if not title or not content:
            return JsonResponse(
                {'error': f'No registered exporter for {product}:{record_type}. '
                          'Provide title and content in POST data.'},
                status=400,
            )
        item = submit_to_foia(
            source_product=product,
            record_type=record_type,
            record_id=record_id,
            title=title,
            content=content,
            submitted_by=request.user,
            foia_request_id=foia_request_id,
        )

    logger.info(
        'User %s exported %s:%s:%s to FOIA queue (item %s)',
        request.user, product, record_type, record_id, item.pk,
    )

    return JsonResponse({
        'status': 'exported',
        'item_id': str(item.pk),
        'message': f'{record_type} exported for FOIA review.',
    })
