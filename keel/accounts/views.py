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
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, Q
from django.template.loader import render_to_string
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from keel.core.utils import rate_limit

from .models import (
    Agency, Invitation, KeelUser, Organization, OrganizationProductSubscription,
    ProductAccess, get_product_choices, get_product_roles,
)


# Session key for the dokadmin (cross-org superuser) "currently editing
# this org" selector. Reads/writes go through this constant so the view
# layer and any future tests speak the same key.
SUPERUSER_ORG_SESSION_KEY = 'keel_admin_target_org_id'


def _resolve_inviter_org(request):
    """Determine which Organization an admin's invitations should bind to.

    **Implementation invariant (CSO finding S5):** the target org MUST
    be derived server-side from ``request.user.organization`` for
    non-superusers. The ``organization`` POST field is read ONLY when
    ``request.user.is_superuser`` is True, and the value MUST be an
    active org id resolved via the session (not a hidden form field).
    For non-superusers, the field is ignored entirely — never trusted,
    never echoed.

    Returns ``(organization, error_message)``. ``organization=None``
    only when the admin is a superuser who hasn't selected an org yet
    AND no default could be inferred (in which case the caller should
    surface ``error_message`` and not create any invitations).
    """
    if not request.user.is_superuser:
        # Non-superuser: their org is the only legal target. Reading
        # the POST field would open a tampered-form path; we just
        # ignore anything sent.
        org = request.user.organization
        if org is None:
            # Defensive — the model invariant blocks this state, but
            # callers should still get a clean error if it ever happens.
            return None, (
                'Your account is not assigned to an organization. '
                'Contact a DockLabs admin.'
            )
        return org, None

    # Superuser path. The org is selected via the session (set on the
    # invitation_list page via the dokadmin org dropdown). NEVER read
    # from POST: a stolen dokadmin session shouldn't be able to
    # silently switch orgs mid-invitation.
    target_id = request.session.get(SUPERUSER_ORG_SESSION_KEY)
    if target_id:
        try:
            return Organization.objects.get(pk=target_id, is_active=True), None
        except Organization.DoesNotExist:
            pass
    # Fall back to the superuser's own organization (e.g. dokadmin's
    # personal org, if one was assigned). If they don't have one, the
    # admin has to pick one before sending invites.
    if request.user.organization_id:
        return request.user.organization, None
    return None, (
        'No target organization selected. Choose one from the org '
        'switcher at the top of the invitations page.'
    )

logger = logging.getLogger(__name__)


def _admin_check(user):
    """Check if user is a Keel admin.

    Three role tiers grant admin-console access:
      - ``system_admin`` / ``admin`` — IT-level platform admins (DockLabs).
      - ``agency_admin`` — customer-side admin who manages their own org's
        users. Cannot grant other admin-tier roles (enforced separately
        in ``available_grantable_roles`` / ``send_invitation``).
    Superusers always pass.
    """
    if user.is_superuser:
        return True
    return ProductAccess.objects.filter(
        user=user,
        role__in=('admin', 'system_admin', 'agency_admin'),
        is_active=True,
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
        count = KeelUser.objects.filter(
            Q(is_superuser=True) | Q(product_access__product=value, product_access__is_active=True),
            is_active=True,
        ).distinct().count()
        product_stats.append({
            'code': value, 'name': label,
            'user_count': count,
        })

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

    # Mirror the invitation matrix gate: agency_admin cannot grant
    # protected admin-tier roles via the direct-grant surface either.
    from keel.accounts.services import available_grantable_roles
    grantable = {slug for slug, _ in available_grantable_roles(request.user, product)}
    if role not in grantable:
        messages.error(
            request,
            f'You are not authorized to grant the "{role}" role for {product}. '
            'Ask a system admin to grant admin-tier roles.',
        )
        logger.warning(
            'ROLE_GRANT_DENIED: user=%s org=%s tried to grant role=%s product=%s '
            'to user=%s via direct grant — admin-tier escalation blocked',
            request.user.username,
            request.user.organization_id,
            role, product, target_user.username,
        )
        try:
            from django.apps import apps as django_apps
            audit_path = getattr(
                settings, 'KEEL_AUDIT_LOG_MODEL', 'keel_accounts.AuditLog',
            )
            AuditLog = django_apps.get_model(audit_path)
            AuditLog.objects.create(
                user=request.user,
                action='role_grant_denied',
                entity_type='ProductAccess',
                entity_id=str(target_user.pk),
                description=(
                    f'Actor {request.user.username} attempted to grant '
                    f'{product}/{role} to {target_user.username}; blocked.'
                ),
                changes={
                    'product': product,
                    'role': role,
                    'target_user_id': str(target_user.pk),
                    'actor_org_id': str(request.user.organization_id),
                },
                ip_address=getattr(request, 'audit_ip', None),
            )
        except Exception:  # pragma: no cover
            logger.exception('Failed to write role_grant_denied audit row')
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
    """List all invitations with status filtering, scoped to the inviter's org.

    The matrix on this page only renders products the inviter's org
    actively subscribes to (CSO + eng-review intent). Products outside
    the org's subscription set are not greyed out — they are not in
    the form at all. Server-side validation in ``send_invitation``
    enforces the same gate against POSTed values.
    """
    # Allow superusers to switch the active target org via ?org=<slug>
    # so the matrix updates without rebuilding the form. Persists in
    # the session so subsequent POSTs see the selection. Ignored
    # entirely for non-superusers (their org is already pinned).
    if request.user.is_superuser:
        requested = request.GET.get('org', '').strip()
        if requested:
            try:
                org = Organization.objects.get(slug=requested, is_active=True)
                request.session[SUPERUSER_ORG_SESSION_KEY] = str(org.pk)
            except Organization.DoesNotExist:
                messages.warning(request, f"Organization '{requested}' not found.")

    target_org, target_org_error = _resolve_inviter_org(request)
    subscribed_codes = (
        OrganizationProductSubscription.active_product_codes(target_org)
        if target_org else []
    )

    status = request.GET.get('status', '').strip()
    invitations = Invitation.objects.select_related(
        'invited_by', 'accepted_by', 'organization',
    )

    # Non-superusers see only their own org's invitations. dokadmin
    # sees everything (with org column rendered in the table).
    if not request.user.is_superuser and target_org is not None:
        invitations = invitations.filter(organization=target_org)

    if status:
        invitations = invitations.filter(status=status)

    # Filter the role choices the actor is allowed to grant. Agency
    # admins see operator roles only — the protected admin tier is
    # stripped from the matrix so the form can't even render an
    # escalation option. System admins / superusers see everything.
    from keel.accounts.services import available_grantable_roles
    all_roles = {
        product: available_grantable_roles(request.user, product)
        for product in get_product_roles().keys()
    }
    all_roles['all'] = available_grantable_roles(request.user, 'all')

    # Render only subscribed products in the matrix. Products outside
    # the subscription set are absent (not greyed out) so the admin's
    # mental model is "what *we* can grant", not "what could exist."
    all_products = list(get_product_choices())
    matrix_products = [
        (code, label) for code, label in all_products if code in subscribed_codes
    ]
    unsubscribed = [
        label for code, label in all_products if code not in subscribed_codes
    ]

    context = {
        'invitations': invitations.order_by('-created_at')[:100],
        'selected_status': status,
        'products': matrix_products,
        'unsubscribed_products': unsubscribed,
        'product_roles': all_roles,
        'product_roles_json': json.dumps(all_roles),
        'target_org': target_org,
        'target_org_error': target_org_error,
        # For the dokadmin org-switcher dropdown.
        'available_orgs': (
            list(Organization.objects.filter(is_active=True).order_by('name'))
            if request.user.is_superuser else []
        ),
    }
    return render(request, 'accounts/invitation_list.html', context)


@admin_required
@require_POST
def send_invitation(request):
    """Create per-product invitations from the matrix form.

    Subscription gating: the inviter's organization must actively
    subscribe to every product in the POSTed ``products`` list. Out-
    of-set products are dropped server-side; the user gets a clear
    error rather than a silently-ignored selection.

    Cross-org dokadmin invites (where the inviter is a superuser AND
    the selected target org is NOT the inviter's own org) are flagged
    in the audit log at HIGH priority as the interim mitigation for
    CSO finding S3 (a follow-up PR will add Django sudo-mode here).
    """
    target_org, target_org_error = _resolve_inviter_org(request)
    if target_org is None:
        messages.error(request, target_org_error or 'No target organization.')
        return redirect('keel_accounts:invitation_list')

    email = request.POST.get('email', '').strip().lower()
    if not email:
        messages.error(request, 'Email is required.')
        return redirect('keel_accounts:invitation_list')

    selected = request.POST.getlist('products')
    if not selected:
        messages.error(request, 'Select at least one product.')
        return redirect('keel_accounts:invitation_list')

    # Server-side subscription validation (CSO finding S5). Filter the
    # POSTed list against the org's active subscription set; record any
    # tampered/stale entries as ``unsubscribed`` for a clean error.
    subscribed_codes = OrganizationProductSubscription.active_product_codes(
        target_org
    )
    unsubscribed_attempts = [p for p in selected if p not in subscribed_codes]
    selected = [p for p in selected if p in subscribed_codes]

    if unsubscribed_attempts:
        messages.error(
            request,
            f'Your organization "{target_org.name}" is not subscribed to: '
            f'{", ".join(unsubscribed_attempts)}. Those invitations were not '
            f'created. Contact DockLabs to add the subscription.',
        )

    if not selected:
        # All POSTed products were filtered out as unsubscribed. The
        # error above already explains why; just bounce.
        return redirect('keel_accounts:invitation_list')

    # Cross-org dokadmin detection: log HIGH-priority audit row so a
    # compromised superuser session is detectable in the audit stream.
    is_cross_org = (
        request.user.is_superuser
        and request.user.organization_id is not None
        and request.user.organization_id != target_org.id
    )
    if is_cross_org:
        logger.warning(
            'CROSS_ORG_INVITATION: superuser=%s home_org=%s target_org=%s '
            'invited=%s products=%s — review for compromise',
            request.user.username,
            request.user.organization_id,
            target_org.id,
            email,
            selected,
        )
        # Best-effort AuditLog row tagged "cross_org_invitation". The
        # field set matches the standard audit pattern; downstream
        # tooling can filter on action='cross_org_invitation' and
        # alert on it.
        try:
            from django.apps import apps as django_apps
            audit_path = getattr(
                settings, 'KEEL_AUDIT_LOG_MODEL', 'keel_accounts.AuditLog',
            )
            AuditLog = django_apps.get_model(audit_path)
            AuditLog.objects.create(
                user=request.user,
                action='cross_org_invitation',
                entity_type='Organization',
                entity_id=str(target_org.id),
                description=(
                    f'Superuser {request.user.username} invited {email} '
                    f'to org {target_org.slug} (products: {", ".join(selected)})'
                ),
                changes={
                    'target_org': target_org.slug,
                    'home_org_id': str(request.user.organization_id),
                    'invited_email': email,
                    'products': selected,
                },
                ip_address=getattr(request, 'audit_ip', None),
            )
        except Exception:  # pragma: no cover — best-effort
            logger.exception('Failed to write cross-org invitation audit row')

    days = getattr(settings, 'KEEL_INVITATION_EXPIRY_DAYS', 7)
    expires_at = timezone.now() + timedelta(days=days)
    batch_id = uuid.uuid4()

    # Per-actor allowlist of grantable roles. Agency admins cannot grant
    # protected admin-tier roles; this is the load-bearing server-side
    # check that mirrors the matrix render filter.
    from keel.accounts.services import available_grantable_roles
    grantable = {
        prod: {slug for slug, _label in available_grantable_roles(request.user, prod)}
        for prod in selected
    }

    created_invitations = []
    skipped = []
    invalid = []
    denied = []
    for prod in selected:
        role = request.POST.get(f'role__{prod}', '').strip()
        valid_roles = {r for r, _ in get_product_roles(prod) or []}
        if role not in valid_roles:
            invalid.append(prod)
            continue
        if role not in grantable.get(prod, set()):
            denied.append((prod, role))
            continue
        is_beta = request.POST.get(f'beta__{prod}') == '1'

        if Invitation.objects.filter(
            email=email, product=prod, status='pending',
        ).exists():
            skipped.append(prod)
            continue

        created_invitations.append(Invitation.objects.create(
            email=email,
            product=prod,
            role=role,
            is_beta_tester=is_beta,
            batch_id=batch_id,
            invited_by=request.user,
            organization=target_org,
            expires_at=expires_at,
        ))

    if denied:
        denied_summary = ', '.join(f'{prod} ({role})' for prod, role in denied)
        messages.error(
            request,
            f'You are not authorized to grant admin-tier roles. Denied: '
            f'{denied_summary}. Ask a system admin to grant these.',
        )
        logger.warning(
            'ROLE_GRANT_DENIED: user=%s org=%s tried to grant protected role(s) '
            '%s to %s — admin-tier role-grant escalation blocked',
            request.user.username,
            request.user.organization_id,
            denied,
            email,
        )
        try:
            from django.apps import apps as django_apps
            audit_path = getattr(
                settings, 'KEEL_AUDIT_LOG_MODEL', 'keel_accounts.AuditLog',
            )
            AuditLog = django_apps.get_model(audit_path)
            AuditLog.objects.create(
                user=request.user,
                action='role_grant_denied',
                entity_type='Invitation',
                entity_id=email,
                description=(
                    f'Actor {request.user.username} attempted to grant protected '
                    f'admin-tier role(s) {denied_summary} to {email}; blocked '
                    f'by available_grantable_roles gate.'
                ),
                changes={
                    'denied_grants': [
                        {'product': prod, 'role': role} for prod, role in denied
                    ],
                    'invited_email': email,
                    'actor_org_id': str(request.user.organization_id),
                },
                ip_address=getattr(request, 'audit_ip', None),
            )
        except Exception:  # pragma: no cover — best-effort
            logger.exception('Failed to write role_grant_denied audit row')

    if invalid:
        messages.error(
            request,
            f'Invalid role for: {", ".join(invalid)}.',
        )
    if skipped:
        messages.warning(
            request,
            f'Pending invitation already exists for {email} → {", ".join(skipped)}.',
        )
    if created_invitations:
        # Any token in the batch accepts the whole batch — pick the first.
        accept_url = request.build_absolute_uri(
            f'/invite/{created_invitations[0].token}/'
        )
        product_lines = [
            f'  • {inv.product.title()} — {inv.role}'
            f'{" (beta tester)" if inv.is_beta_tester else ""}'
            for inv in created_invitations
        ]
        product_names = ', '.join(
            f'{inv.product} ({inv.role})' for inv in created_invitations
        )

        # Send the actual invitation email — DockLabs-branded HTML + plaintext
        # fallback. Bypasses the notification-channel email path because invites
        # are pre-account: the recipient has no NotificationPreference yet.
        try:
            inviter_name = request.user.get_full_name() or request.user.email
            expiry_days = getattr(settings, 'KEEL_INVITATION_EXPIRY_DAYS', 7)
            ctx = {
                'inviter_name': inviter_name,
                'invitee_email': email,
                'batch_invitations': created_invitations,
                'accept_url': accept_url,
                'expiry_days': expiry_days,
                'site_name': 'DockLabs',
            }
            text_body = render_to_string('accounts/emails/invitation.txt', ctx)
            html_body = render_to_string('accounts/emails/invitation.html', ctx)
            subject = (
                f'{inviter_name} invited you to DockLabs'
                f' ({len(created_invitations)} product{"s" if len(created_invitations) != 1 else ""})'
            )
            mail = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                to=[email],
            )
            mail.attach_alternative(html_body, 'text/html')
            mail.send(fail_silently=False)
            email_sent = True
        except Exception as exc:  # noqa: BLE001 — best-effort; surface to admin
            logger.exception('Failed to send invitation email to %s: %s', email, exc)
            email_sent = False

        if email_sent:
            messages.success(
                request,
                f'Sent invitation email to {email} → {product_names}.',
            )
        else:
            messages.warning(
                request,
                f'Invitations created for {email} → {product_names}, but the '
                f'email failed to send. Accept link: {accept_url}',
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
@require_POST
def accept_invitation_signout(request, token):
    """Sign out the current user across the WHOLE suite, then bounce
    back to /invite/<token>/.

    Critical UX subtlety: the mismatch page is rendered when a
    logged-in user clicks an invite addressed to someone else. The
    user has stale sessions across the suite (Helm, Beacon, Harbor,
    etc.) — each product holds its own subdomain-scoped session
    cookie. Just clearing keel's session would leave the user "still
    signed in as dok@" on Helm and every other product, even after
    they create the new account here.

    Fix: stamp ``last_logout_at`` on the User row before calling
    ``logout()``. Each product's ``SessionFreshnessMiddleware`` polls
    Keel's ``/oauth/session-status/`` on the next request, compares
    that timestamp against the session's ``keel_oidc_login_at``, and
    tears down the stale per-product session when keel's logout is
    newer. The user is bounced to login, AutoOIDCLoginMiddleware
    starts an OIDC flow against keel (where they're now logged in as
    the invitation's email after acceptance), and lands logged in as
    the right person across every suite product.

    Validates the token exists before logging out so a bogus token
    doesn't trigger session destruction.
    """
    # Cheap existence check — don't tear down the session if the token
    # is bogus. We don't reveal status (expired, revoked, accepted) to
    # avoid token-probing leaks.
    get_object_or_404(Invitation, token=token)
    # Stamp the suite-wide logout epoch BEFORE clearing the keel
    # session — same pattern as keel.core.views.suite_logout_endpoint.
    # .update() is atomic, skips signal noise, and avoids a needless
    # full save() round-trip.
    if request.user.is_authenticated:
        KeelUser.objects.filter(pk=request.user.pk).update(
            last_logout_at=timezone.now(),
        )
    logout(request)
    return redirect(f'/invite/{token}/')


def accept_invitation_complete(request, token):
    """Post-acceptance interstitial that clears stale per-product
    sessions before the final redirect to the suite landing page.

    The flow this exists to fix: user A accepts an invitation while
    user B (e.g. an admin) was previously signed in on the same browser
    across other suite products (Helm, Beacon, etc.). Each product
    holds its own subdomain-scoped session cookie. Even after the
    user's keel session is replaced (because they accepted as user A),
    each product's session middleware would still see user B until its
    next freshness-cache miss — up to 60 seconds — by which point the
    user has likely concluded "nothing happened."

    Solution: render an interstitial page with hidden <img> beacons
    pointing at each product's /accounts/logout/ URL. Browsers fire
    same-site GETs (SameSite=Lax cookies for *.docklabs.ai products
    flow on top-level navigations including image loads), each
    product's SuiteLogoutView destroys its session cookie, and the
    user's onward navigation hits a clean slate. After ~2.5s the
    interstitial JS-redirects to KEEL_INVITATION_LANDING_URL where the
    AutoOIDCLoginMiddleware will start a fresh OIDC sign-in as the
    just-created identity.

    Validates the token exists so this URL can't be used to spam
    logout requests at every product.
    """
    invitation = get_object_or_404(Invitation, token=token)
    landing_url = getattr(
        settings,
        'KEEL_INVITATION_LANDING_URL',
        getattr(settings, 'LOGIN_REDIRECT_URL', '/dashboard/'),
    )
    # Pull product list directly from KEEL_FLEET_PRODUCTS — same source
    # of truth used by the fleet switcher, so nothing drifts.
    fleet = getattr(settings, 'KEEL_FLEET_PRODUCTS', []) or []
    # Strip the trailing /dashboard/ — we want the host root for the
    # logout URL, not the product's dashboard.
    logout_urls = []
    for entry in fleet:
        url = (entry.get('url') or '').rstrip('/')
        if url.endswith('/dashboard'):
            url = url[: -len('/dashboard')]
        if url:
            logout_urls.append(f'{url}/accounts/logout/')
    return render(request, 'accounts/invitation_complete.html', {
        'invitation': invitation,
        'landing_url': landing_url,
        'logout_urls': logout_urls,
    })


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

    # Email-mismatch guard: if a different user is logged in, refuse to
    # silently accept this invite onto their account. The recipient must
    # sign out and accept as themselves (or the invite must be reissued).
    # Match case-insensitively because email is identity-grade.
    if (
        request.user.is_authenticated
        and (request.user.email or '').lower() != (invitation.email or '').lower()
    ):
        return render(request, 'accounts/invitation_mismatch.html', {
            'invitation': invitation,
            'logged_in_email': request.user.email,
        }, status=403)

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

            # AUTH_PASSWORD_VALIDATORS is only invoked by form .clean_password()
            # or an explicit validate_password() call — create_user() skips it.
            try:
                validate_password(
                    password,
                    user=KeelUser(
                        username=username,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                    ),
                )
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
                return render(request, 'accounts/accept_invitation.html', {
                    'invitation': invitation,
                })

            user = KeelUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        # Grant product access — accept the whole batch if this invitation
        # was part of a multi-product invite, otherwise just this one row.
        if invitation.batch_id:
            siblings = list(Invitation.objects.filter(
                batch_id=invitation.batch_id,
                email=invitation.email,
                status='pending',
            ))
        else:
            siblings = [invitation]

        accepted = []
        for inv in siblings:
            if inv.is_usable:
                inv.accept(user)
                accepted.append(inv.product)

        if len(accepted) == 1:
            messages.success(
                request,
                f'Welcome! You now have access to {accepted[0]}.',
            )
        else:
            messages.success(
                request,
                f'Welcome! You now have access to: {", ".join(accepted)}.',
            )

        # Bounce through the suite-clear interstitial before the final
        # landing redirect. The interstitial fires hidden <img> beacons
        # at every product's /accounts/logout/ to destroy any stale
        # per-product sessions the just-accepted user (or anyone else
        # logged in on this browser) might still be carrying. Without
        # this, a user who arrived via the mismatch flow lands on Helm
        # still showing the OLD identity for up to 60 seconds (the
        # SessionFreshnessMiddleware cache TTL).
        return redirect(f'/invite/{token}/complete/')

    # GET: list all sibling invitations in the batch so the recipient sees
    # the full set they're about to accept.
    if invitation.batch_id:
        batch_invitations = list(Invitation.objects.filter(
            batch_id=invitation.batch_id,
            email=invitation.email,
            status='pending',
        ))
    else:
        batch_invitations = [invitation]

    return render(request, 'accounts/accept_invitation.html', {
        'invitation': invitation,
        'batch_invitations': batch_invitations,
        'user_exists': request.user.is_authenticated,
    })

# ---------------------------------------------------------------------------
# Username availability — JSON API for the live profile-form check
# ---------------------------------------------------------------------------
@require_GET
@login_required
@rate_limit(max_requests=30, window=60)
def username_available(request):
    """Return whether ``?u=<candidate>`` is a free username.

    Response shape (always 200, errors are encoded in the body so the JS
    can render them inline):

        {"available": bool, "reason": str | null, "normalized": str}

    ``reason`` is one of: ``"taken"``, ``"reserved"``, ``"invalid_format"``,
    ``"unchanged"``, or ``null`` on success. ``normalized`` is the
    lowercased / trimmed candidate the server actually evaluated, so the
    JS can mirror it back into the input if the user typed mixed case.

    Rate-limited to 30 req/min/IP to discourage username enumeration —
    the form-debounce keystroke rate is well below this in normal use.
    """
    from .forms import validate_username_format

    candidate = (request.GET.get("u") or "").strip().lower()
    payload = {"available": False, "reason": None, "normalized": candidate}

    if not candidate:
        payload["reason"] = "invalid_format"
        return JsonResponse(payload)

    err = validate_username_format(candidate)
    if err is not None:
        payload["reason"] = err
        return JsonResponse(payload)

    if candidate == request.user.username:
        # Not "taken" by someone else, but not a meaningful change either.
        # Treat as a distinct state so the JS can render a neutral hint
        # rather than a green check.
        payload["reason"] = "unchanged"
        return JsonResponse(payload)

    if KeelUser.objects.filter(username__iexact=candidate).exclude(pk=request.user.pk).exists():
        payload["reason"] = "taken"
        return JsonResponse(payload)

    payload["available"] = True
    return JsonResponse(payload)



# ---------------------------------------------------------------------------
# Email change confirmation — keel-native flow (Keel IdP without allauth)
# ---------------------------------------------------------------------------
@require_GET
def confirm_email_change(request, token: str):
    """Confirm a PendingEmailChange via the click-through link.

    Renders an explanatory page on every outcome (success/expired/etc.)
    rather than redirecting silently — users who clicked stale links
    deserve a clear "this expired" message instead of a mystery redirect.
    """
    from .services import confirm_email_change as _confirm
    result = _confirm(token)
    return render(
        request,
        'accounts/email_change/confirm_result.html',
        {'result': result},
        status=200 if result['ok'] else 400,
    )
