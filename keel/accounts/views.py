"""Keel accounts admin console — manage users, product access, invitations.

These views are protected by @admin_required. Include them in your
product's urls.py:

    from keel.accounts.urls import urlpatterns as accounts_urls
    urlpatterns = [
        path('accounts/', include(accounts_urls)),
    ]
"""
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Agency, Invitation, KeelUser, ProductAccess,
    get_product_choices, get_product_roles,
)

logger = logging.getLogger(__name__)


def _admin_check(user):
    """Check if user is a Keel admin (superuser or admin role in any product)."""
    if user.is_superuser:
        return True
    return ProductAccess.objects.filter(
        user=user, role__in=('admin', 'system_admin'), is_active=True,
    ).exists()


def admin_required(view_func):
    """Require Keel admin access."""
    from functools import wraps

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not _admin_check(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@admin_required
def dashboard(request):
    """Admin console home — overview of users and products."""
    product_choices = get_product_choices()
    product_stats = []
    for value, label in product_choices:
        count = ProductAccess.objects.filter(product=value, is_active=True).count()
        product_stats.append({'code': value, 'name': label, 'user_count': count})

    context = {
        'total_users': KeelUser.objects.filter(is_active=True).count(),
        'total_invitations': Invitation.objects.filter(status='pending').count(),
        'products': product_stats,
        'recent_users': KeelUser.objects.order_by('-created_at')[:10],
    }
    return render(request, 'accounts/dashboard.html', context)


# ---------------------------------------------------------------------------
# User list & detail
# ---------------------------------------------------------------------------
@admin_required
def user_list(request):
    """List all users with search and product filtering."""
    q = request.GET.get('q', '').strip()
    product = request.GET.get('product', '').strip()

    users = KeelUser.objects.filter(is_active=True).select_related('agency')

    if q:
        users = users.filter(
            Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(username__icontains=q)
        )

    if product:
        user_ids = ProductAccess.objects.filter(
            product=product, is_active=True,
        ).values_list('user_id', flat=True)
        users = users.filter(id__in=user_ids)

    users = users.prefetch_related('product_access').annotate(
        product_count=Count('product_access', filter=Q(product_access__is_active=True))
    ).order_by('last_name', 'first_name')

    context = {
        'users': users,
        'search_query': q,
        'selected_product': product,
        'products': get_product_choices(),
    }
    return render(request, 'accounts/user_list.html', context)


@admin_required
def user_detail(request, user_id):
    """View and manage a single user's profile and product access."""
    target_user = get_object_or_404(KeelUser, pk=user_id)
    access_list = target_user.product_access.all().order_by('product')

    all_roles = get_product_roles()
    context = {
        'target_user': target_user,
        'access_list': access_list,
        'products': get_product_choices(),
        'product_roles': all_roles,
        'product_roles_json': json.dumps(all_roles),
    }
    return render(request, 'accounts/user_detail.html', context)


# ---------------------------------------------------------------------------
# Product access management
# ---------------------------------------------------------------------------
@admin_required
@require_POST
def grant_access(request, user_id):
    """Grant a user access to a product with a specific role."""
    target_user = get_object_or_404(KeelUser, pk=user_id)
    product = request.POST.get('product', '').strip()
    role = request.POST.get('role', '').strip()

    if not product or not role:
        messages.error(request, 'Product and role are required.')
        return redirect('keel_accounts:user_detail', user_id=user_id)

    access, created = ProductAccess.objects.update_or_create(
        user=target_user,
        product=product,
        defaults={
            'role': role,
            'is_active': True,
            'granted_by': request.user,
        },
    )

    action = 'granted' if created else 'updated'
    messages.success(
        request,
        f'Product access {action}: {target_user} → {product} ({role})',
    )
    logger.info(
        'Admin %s %s product access: %s → %s (%s)',
        request.user, action, target_user, product, role,
    )
    return redirect('keel_accounts:user_detail', user_id=user_id)


@admin_required
@require_POST
def revoke_access(request, access_id):
    """Revoke a user's access to a product."""
    access = get_object_or_404(ProductAccess, pk=access_id)
    user_id = access.user_id
    access.is_active = False
    access.save(update_fields=['is_active'])

    messages.success(request, f'Revoked {access.user} access to {access.product}.')
    logger.info('Admin %s revoked product access: %s', request.user, access)
    return redirect('keel_accounts:user_detail', user_id=user_id)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------
@admin_required
def invitation_list(request):
    """List all invitations with status filtering."""
    status = request.GET.get('status', '').strip()
    invitations = Invitation.objects.select_related('invited_by', 'accepted_by')

    if status:
        invitations = invitations.filter(status=status)

    all_roles = get_product_roles()
    all_roles['all'] = get_product_roles('all')
    context = {
        'invitations': invitations.order_by('-created_at')[:100],
        'selected_status': status,
        'products': get_product_choices(),
        'product_roles': all_roles,
        'product_roles_json': json.dumps(all_roles),
    }
    return render(request, 'accounts/invitation_list.html', context)


@admin_required
@require_POST
def send_invitation(request):
    """Create and send an invitation to a new or existing user."""
    email = request.POST.get('email', '').strip().lower()
    product = request.POST.get('product', '').strip()
    role = request.POST.get('role', '').strip()
    is_beta_tester = request.POST.get('is_beta_tester') == '1'

    if not email or not product or not role:
        messages.error(request, 'Email, product, and role are required.')
        return redirect('keel_accounts:invitation_list')

    days = getattr(settings, 'KEEL_INVITATION_EXPIRY_DAYS', 7)
    expires_at = timezone.now() + timedelta(days=days)

    # "all" = invite to every product in the suite
    if product == 'all':
        products_to_invite = [
            code for code, _ in get_product_choices() if code != 'keel'
        ]
    else:
        products_to_invite = [product]

    created_invitations = []
    skipped = []
    for prod in products_to_invite:
        existing = Invitation.objects.filter(
            email=email, product=prod, status='pending',
        ).first()
        if existing:
            skipped.append(prod)
            continue

        inv = Invitation.objects.create(
            email=email,
            product=prod,
            role=role,
            is_beta_tester=is_beta_tester,
            invited_by=request.user,
            expires_at=expires_at,
        )
        created_invitations.append(inv)

    if skipped:
        messages.warning(
            request,
            f'Pending invitation already exists for {email} → {", ".join(skipped)}.',
        )

    if created_invitations:
        # Use the first invitation's token for the link
        invite_url = request.build_absolute_uri(
            f'/invite/{created_invitations[0].token}/'
        )
        product_names = ', '.join(inv.product for inv in created_invitations)
        messages.success(
            request,
            f'Invitation created for {email} → {product_names} ({role}). '
            f'Share this link: {invite_url}',
        )
        logger.info('Admin %s created invitation(s): %s', request.user, created_invitations)

    return redirect('keel_accounts:invitation_list')


@admin_required
@require_POST
def revoke_invitation(request, invitation_id):
    """Revoke a pending invitation."""
    invitation = get_object_or_404(Invitation, pk=invitation_id)
    invitation.revoke()
    messages.success(request, f'Invitation to {invitation.email} revoked.')
    return redirect('keel_accounts:invitation_list')


# ---------------------------------------------------------------------------
# Invitation acceptance (public-facing)
# ---------------------------------------------------------------------------
def accept_invitation(request, token):
    """Public view for accepting an invitation via email link.

    GET: Show invitation details and signup/login form.
    POST: Accept the invitation and grant product access.
    """
    invitation = get_object_or_404(Invitation, token=token)

    if not invitation.is_usable:
        return render(request, 'accounts/invitation_expired.html', {
            'invitation': invitation,
        })

    if request.method == 'POST':
        if request.user.is_authenticated:
            user = request.user
        else:
            # Create new account from invitation
            email = invitation.email
            password = request.POST.get('password', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()

            if not password:
                messages.error(request, 'Password is required.')
                return render(request, 'accounts/accept_invitation.html', {
                    'invitation': invitation,
                })

            # Check if account already exists
            existing = KeelUser.objects.filter(email__iexact=email).first()
            if existing:
                messages.info(
                    request,
                    'An account with this email already exists. '
                    'Please log in first, then visit this link again.',
                )
                return redirect(f'/accounts/login/?next=/invite/{token}/')

            username = email.split('@')[0].lower().replace('.', '_')
            counter = 1
            base = username
            while KeelUser.objects.filter(username=username).exists():
                username = f'{base}_{counter}'
                counter += 1

            user = KeelUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        # Grant product access
        access = invitation.accept(user)
        messages.success(
            request,
            f'Welcome! You now have access to {invitation.product}.',
        )

        # Redirect to the product
        redirect_url = getattr(settings, 'LOGIN_REDIRECT_URL', '/dashboard/')
        return redirect(redirect_url)

    return render(request, 'accounts/accept_invitation.html', {
        'invitation': invitation,
        'user_exists': request.user.is_authenticated,
    })
