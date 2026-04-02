"""Change request views — submission API and admin review console.

Two audiences:
1. Beta users: submit requests via form or API from within any product.
2. Admin (Daniel): review, approve/decline, copy Claude Code prompt.

Products submit change requests to Keel via the /api/requests/ingest/
endpoint, authenticated with a shared API key (KEEL_API_KEY env var).
The widget in each product uses fetch() to POST JSON to this endpoint.
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Category, ChangeRequest, Priority, Status

logger = logging.getLogger(__name__)


def _admin_check(user):
    """Check if user is a Keel admin."""
    if user.is_superuser:
        return True
    try:
        from keel.accounts.models import ProductAccess
        return ProductAccess.objects.filter(
            user=user, role__in=('admin', 'system_admin'), is_active=True,
        ).exists()
    except Exception:
        return getattr(user, 'role', None) in ('admin', 'system_admin')


def admin_required(view_func):
    from functools import wraps

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not _admin_check(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


# =========================================================================
# Beta user submission
# =========================================================================
@login_required
@require_POST
def submit_request(request):
    """Submit a change request from within a product.

    Accepts both form POST and JSON POST.
    """
    content_type = request.content_type or ''

    if 'json' in content_type:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
    else:
        data = request.POST

    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    category = (data.get('category') or Category.FEATURE).strip()
    priority = (data.get('priority') or Priority.MEDIUM).strip()
    product = (
        data.get('product')
        or getattr(settings, 'KEEL_PRODUCT_NAME', '')
    ).strip().lower()
    page_url = (data.get('page_url') or '').strip()

    if not title or not description:
        if 'json' in content_type:
            return JsonResponse({'error': 'Title and description are required.'}, status=400)
        messages.error(request, 'Title and description are required.')
        return redirect(request.META.get('HTTP_REFERER', '/'))

    cr = ChangeRequest.objects.create(
        submitted_by=request.user,
        submitted_by_name=str(request.user),
        submitted_by_email=getattr(request.user, 'email', ''),
        product=product,
        title=title,
        description=description,
        category=category,
        priority=priority,
        page_url=page_url,
    )

    # Notify admins
    _notify_admins(cr, request)

    logger.info('Change request submitted: %s by %s', cr.title, request.user)

    if 'json' in content_type:
        return JsonResponse({
            'id': str(cr.id),
            'status': 'pending',
            'message': 'Your request has been submitted for review.',
        }, status=201)

    messages.success(request, 'Your suggestion has been submitted. We\'ll review it shortly.')
    return redirect(request.META.get('HTTP_REFERER', '/'))


# =========================================================================
# Cross-origin API ingest (products → Keel)
# =========================================================================
@csrf_exempt
@require_POST
def api_ingest(request):
    """Receive a change request from any DockLabs product.

    Products POST JSON to https://keel.docklabs.ai/api/requests/ingest/
    with header: Authorization: Bearer <KEEL_API_KEY>

    This is the primary path for change requests to reach Keel's database.
    The widget in each product uses fetch() to call this endpoint.
    """
    # Verify API key
    api_key = getattr(settings, 'KEEL_API_KEY', '') or ''
    if not api_key:
        return JsonResponse({'error': 'API ingest not configured.'}, status=503)

    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer ') or not hmac.compare_digest(
        auth_header[7:].strip(), api_key
    ):
        return JsonResponse({'error': 'Invalid API key.'}, status=401)

    # Parse JSON body
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    if not title or not description:
        return JsonResponse({'error': 'Title and description are required.'}, status=400)

    cr = ChangeRequest.objects.create(
        submitted_by=None,  # No local user on Keel; identity captured below
        submitted_by_name=(data.get('submitted_by_name') or 'Unknown').strip(),
        submitted_by_email=(data.get('submitted_by_email') or '').strip(),
        product=(data.get('product') or 'unknown').strip().lower(),
        title=title,
        description=description,
        category=(data.get('category') or Category.FEATURE).strip(),
        priority=(data.get('priority') or Priority.MEDIUM).strip(),
        page_url=(data.get('page_url') or '').strip(),
    )

    logger.info(
        'API ingest: change request "%s" from %s (%s)',
        cr.title, cr.submitted_by_name, cr.product,
    )

    # Return success immediately — notify admins in background thread
    # so SMTP timeouts don't block the API response.
    import threading
    threading.Thread(
        target=_notify_admins_api,
        args=(cr,),
        daemon=True,
    ).start()

    return JsonResponse({
        'id': str(cr.id),
        'status': 'pending',
        'message': 'Your request has been submitted for review.',
    }, status=201)


def _notify_admins_api(cr):
    """Notify Keel admins about a new change request received via API."""
    try:
        from keel.notifications.dispatch import notify
        from keel.accounts.models import KeelUser

        admins = list(KeelUser.objects.filter(
            is_superuser=True, is_active=True,
        ))
        logger.info('Notifying %d admin(s) about change request: %s', len(admins), cr.title)

        if admins:
            result = notify(
                event='change_request_submitted',
                recipients=admins,
                title=f'New {cr.get_category_display()}: {cr.title}',
                message=(
                    f'{cr.submitted_by_name} submitted a '
                    f'{cr.get_category_display().lower()} for '
                    f'{cr.product.title()} from {cr.page_url or "unknown page"}.'
                ),
                priority='medium',
                link=f'/keel/requests/{cr.id}/',
                context={'change_request': cr},
            )
            logger.info('Notification result: sent=%s, skipped=%s, errors=%s, details=%s',
                        result.get('sent'), result.get('skipped'), result.get('errors'),
                        result.get('details'))
        else:
            logger.warning('No active superusers found — cannot notify about change request')
    except Exception:
        logger.exception('Failed to send admin notification for API ingest')


def _notify_admins(cr, request):
    """Send notification to admins about a new change request."""
    try:
        from keel.notifications.dispatch import notify
        from keel.accounts.models import ProductAccess
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin_ids = ProductAccess.objects.filter(
            role__in=('admin', 'system_admin'), is_active=True,
        ).values_list('user_id', flat=True).distinct()
        admins = list(User.objects.filter(pk__in=admin_ids, is_active=True))

        if admins:
            notify(
                event='change_request_submitted',
                actor=request.user,
                recipients=admins,
                title=f'New {cr.get_category_display()}: {cr.title}',
                message=f'{cr.submitted_by_name} submitted a {cr.get_category_display().lower()} for {cr.product.title()}.',
                priority='medium',
                link=f'/keel/requests/{cr.id}/',
                context={'change_request': cr},
            )
    except Exception:
        logger.debug('Could not send admin notification (notifications module may not be configured)')


# =========================================================================
# Admin console: dashboard
# =========================================================================
@admin_required
def dashboard(request):
    """Change request dashboard — overview and pending items."""
    pending = ChangeRequest.objects.filter(status=Status.PENDING)
    approved = ChangeRequest.objects.filter(status=Status.APPROVED)

    # Stats by product
    product_stats = (
        ChangeRequest.objects
        .values('product')
        .annotate(
            total=Count('id'),
            pending_count=Count('id', filter=Q(status=Status.PENDING)),
        )
        .order_by('product')
    )

    # Stats by category
    category_stats = (
        ChangeRequest.objects
        .filter(status=Status.PENDING)
        .values('category')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    context = {
        'pending_requests': pending.order_by('-created_at')[:20],
        'approved_requests': approved.order_by('-reviewed_at')[:10],
        'pending_count': pending.count(),
        'approved_count': approved.count(),
        'total_count': ChangeRequest.objects.count(),
        'implemented_count': ChangeRequest.objects.filter(status=Status.IMPLEMENTED).count(),
        'product_stats': product_stats,
        'category_stats': category_stats,
    }
    return render(request, 'requests/dashboard.html', context)


# =========================================================================
# Admin console: list & detail
# =========================================================================
@admin_required
def request_list(request):
    """Filterable list of all change requests."""
    qs = ChangeRequest.objects.select_related('submitted_by', 'reviewed_by')

    status = request.GET.get('status', '').strip()
    product = request.GET.get('product', '').strip()
    category = request.GET.get('category', '').strip()
    q = request.GET.get('q', '').strip()

    if status:
        qs = qs.filter(status=status)
    if product:
        qs = qs.filter(product=product)
    if category:
        qs = qs.filter(category=category)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    context = {
        'requests': qs.order_by('-created_at')[:100],
        'selected_status': status,
        'selected_product': product,
        'selected_category': category,
        'search_query': q,
        'statuses': Status.choices,
        'categories': Category.choices,
        'priorities': Priority.choices,
    }
    return render(request, 'requests/request_list.html', context)


@admin_required
def request_detail(request, request_id):
    """View a single change request with review controls."""
    cr = get_object_or_404(ChangeRequest, pk=request_id)

    context = {
        'cr': cr,
        'prompt': cr.generate_prompt() if cr.status in (Status.APPROVED, Status.IMPLEMENTING) else None,
        'statuses': Status.choices,
    }
    return render(request, 'requests/request_detail.html', context)


# =========================================================================
# Admin actions: approve / decline / mark implemented
# =========================================================================
@admin_required
@require_POST
def approve_request(request, request_id):
    """Approve a change request."""
    cr = get_object_or_404(ChangeRequest, pk=request_id)
    notes = request.POST.get('admin_notes', '').strip()
    cr.approve(request.user, notes=notes)

    messages.success(request, f'Approved: {cr.title}. Claude Code prompt is ready.')
    logger.info('Admin %s approved change request: %s', request.user, cr.title)

    # Notify the submitter
    _notify_submitter(cr, 'approved')

    return redirect('keel_requests:request_detail', request_id=request_id)


@admin_required
@require_POST
def decline_request(request, request_id):
    """Decline a change request."""
    cr = get_object_or_404(ChangeRequest, pk=request_id)
    reason = request.POST.get('decline_reason', '').strip()
    cr.decline(request.user, reason=reason)

    messages.info(request, f'Declined: {cr.title}')
    logger.info('Admin %s declined change request: %s', request.user, cr.title)

    _notify_submitter(cr, 'declined')

    return redirect('keel_requests:request_detail', request_id=request_id)


@admin_required
@require_POST
def mark_implemented(request, request_id):
    """Mark a request as implemented."""
    cr = get_object_or_404(ChangeRequest, pk=request_id)
    notes = request.POST.get('implementation_notes', '').strip()
    cr.mark_implemented(notes=notes)

    messages.success(request, f'Marked as implemented: {cr.title}')
    _notify_submitter(cr, 'implemented')

    return redirect('keel_requests:request_detail', request_id=request_id)


def _notify_submitter(cr, action):
    """Notify the original submitter about a status change."""
    if not cr.submitted_by_id:
        return
    try:
        from keel.notifications.dispatch import notify
        action_messages = {
            'approved': f'Your request "{cr.title}" has been approved and will be implemented.',
            'declined': f'Your request "{cr.title}" was declined. {cr.decline_reason}',
            'implemented': f'Your request "{cr.title}" has been implemented!',
        }
        notify(
            recipient_id=cr.submitted_by_id,
            title=f'Request {action.title()}: {cr.title}',
            message=action_messages.get(action, f'Request status: {action}'),
            priority='medium',
        )
    except Exception:
        logger.debug('Could not send submitter notification')


# =========================================================================
# API: prompt retrieval (for scripted workflows)
# =========================================================================
@admin_required
def get_prompt(request, request_id):
    """Return the Claude Code prompt as plain text or JSON."""
    cr = get_object_or_404(ChangeRequest, pk=request_id)

    if cr.status not in (Status.APPROVED, Status.IMPLEMENTING):
        return JsonResponse({'error': 'Request must be approved first.'}, status=400)

    cr.mark_implementing()

    if request.GET.get('format') == 'json':
        return JsonResponse({
            'id': str(cr.id),
            'title': cr.title,
            'product': cr.product,
            'prompt': cr.generate_prompt(),
        })

    from django.http import HttpResponse
    return HttpResponse(cr.generate_prompt(), content_type='text/plain; charset=utf-8')
