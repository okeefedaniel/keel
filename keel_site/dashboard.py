"""Platform Activity Dashboard — unified view of all DockLabs activity.

Shows at-a-glance stats, live activity feed, security alerts,
and per-product breakdowns. This is the Keel admin home page.
"""
from collections import Counter
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from keel.accounts.models import AuditLog, KeelUser, ProductAccess, Invitation


def _admin_check(user):
    if user.is_superuser:
        return True
    return ProductAccess.objects.filter(
        user=user, role__in=('admin', 'system_admin'), is_active=True,
    ).exists()


def admin_required(view_func):
    from functools import wraps

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not _admin_check(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


@admin_required
def platform_dashboard(request):
    """Main platform dashboard — the Keel home page for admins."""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # -- User stats --
    total_users = KeelUser.objects.count()
    active_today = (
        AuditLog.objects.filter(
            action='login', timestamp__gte=today_start,
        ).values('user').distinct().count()
    )
    new_this_week = KeelUser.objects.filter(created_at__gte=week_ago).count()

    # -- Product breakdown --
    product_stats = list(
        ProductAccess.objects.filter(is_active=True)
        .values('product')
        .annotate(user_count=Count('user', distinct=True))
        .order_by('-user_count')
    )

    # -- Change requests --
    from keel.requests.models import ChangeRequest, Status
    pending_requests = ChangeRequest.objects.filter(status=Status.PENDING).count()
    approved_requests = ChangeRequest.objects.filter(status=Status.APPROVED).count()
    implemented_this_month = ChangeRequest.objects.filter(
        status=Status.IMPLEMENTED, implemented_at__gte=month_ago,
    ).count()

    # -- Invitations --
    pending_invitations = Invitation.objects.filter(status='pending').count()

    # -- Security --
    security_events = AuditLog.objects.filter(
        action__in=['login_failed', 'security_event'],
        timestamp__gte=week_ago,
    ).count()
    failed_logins_today = AuditLog.objects.filter(
        action='login_failed', timestamp__gte=today_start,
    ).count()

    # -- Activity feed (last 50 events) --
    recent_activity = (
        AuditLog.objects
        .select_related('user')
        .order_by('-timestamp')[:50]
    )

    # -- Logins per day (last 7 days) for chart --
    login_by_day = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        day_start = timezone.make_aware(
            timezone.datetime(day.year, day.month, day.day)
        )
        day_end = day_start + timedelta(days=1)
        count = AuditLog.objects.filter(
            action='login', timestamp__gte=day_start, timestamp__lt=day_end,
        ).values('user').distinct().count()
        login_by_day.append({
            'date': day.strftime('%a'),
            'full_date': day.strftime('%b %d'),
            'count': count,
        })

    # -- Actions by type (last 7 days) for chart --
    action_counts = list(
        AuditLog.objects.filter(timestamp__gte=week_ago)
        .values('action')
        .annotate(count=Count('id'))
        .order_by('-count')[:8]
    )

    context = {
        # Top cards
        'total_users': total_users,
        'active_today': active_today,
        'new_this_week': new_this_week,
        'pending_requests': pending_requests,
        'approved_requests': approved_requests,
        'implemented_this_month': implemented_this_month,
        'pending_invitations': pending_invitations,
        'security_events': security_events,
        'failed_logins_today': failed_logins_today,
        # Product breakdown
        'product_stats': product_stats,
        # Activity feed
        'recent_activity': recent_activity,
        # Chart data
        'login_by_day': login_by_day,
        'action_counts': action_counts,
    }
    return render(request, 'dashboard/platform.html', context)


@admin_required
def activity_feed_api(request):
    """JSON API for live activity feed polling."""
    since = request.GET.get('since')
    limit = min(int(request.GET.get('limit', 50)), 200)

    qs = AuditLog.objects.select_related('user').order_by('-timestamp')

    if since:
        try:
            from django.utils.dateparse import parse_datetime
            since_dt = parse_datetime(since)
            if since_dt:
                qs = qs.filter(timestamp__gt=since_dt)
        except (ValueError, TypeError):
            pass

    product = request.GET.get('product')
    if product:
        qs = qs.filter(product=product)

    action = request.GET.get('action')
    if action:
        qs = qs.filter(action=action)

    entries = []
    for log in qs[:limit]:
        entries.append({
            'id': str(log.pk),
            'user': str(log.user) if log.user else 'System',
            'action': log.action,
            'action_display': log.get_action_display(),
            'entity_type': log.entity_type,
            'entity_id': log.entity_id,
            'description': log.description,
            'product': log.product,
            'ip_address': log.ip_address,
            'timestamp': log.timestamp.isoformat(),
        })

    return JsonResponse({'entries': entries})
