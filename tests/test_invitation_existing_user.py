"""Tests for the existing-user invitation flow.

When ``send_invitation`` receives a POST whose ``email`` already maps to
a ``KeelUser``, the view must:

1. On the first POST, render the confirmation interstitial without
   creating any Invitation rows or sending email.
2. On the re-POST that carries ``acknowledge_existing=1``, drop pure
   no-ops, send the "your access has been updated" email template, and
   create Invitation rows for the changed products.
3. Return ``is_update=True`` from ``accept_invitation`` so the accept
   page renders the review-only branch (no name/password form).
4. Redirect anonymous existing users to ``/accounts/login/`` rather
   than letting them through the new-account form.

Plus a unit check on ``_build_existing_user_diff`` for the four kinds
(role_change, beta_change, reactivate, new_access, noop).
"""
from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone


# The test environment doesn't build a staticfiles manifest, so the
# default ManifestStaticFilesStorage backend raises on every {% static %}
# tag in a rendered template. Disable manifest hashing for the whole
# module — every test here either renders an interstitial or sends an
# email, both of which evaluate static-tag templates.
@pytest.fixture(autouse=True)
def _disable_manifest_storage(settings):
    settings.STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }


def _ack_post(client, payload):
    """Two-step acknowledged POST: phase-1 to get the signed_diff, then
    phase-2 with the signed_diff hidden field. Mirrors what the real
    interstitial form does in the browser. Returns the phase-2 response.

    ``payload`` should NOT include ``acknowledge_existing`` — this helper
    handles the round-trip. Pass everything else verbatim. Pass
    ``_follow=True`` to get a follow-redirect response.
    """
    follow = payload.pop('_follow', False)
    phase1 = client.post(reverse('keel_accounts:send_invitation'), payload)
    assert phase1.status_code == 200, (
        f'phase-1 expected 200 (interstitial), got {phase1.status_code}. '
        'Did the test set up an existing user?'
    )
    signed = phase1.context['signed_diff']
    return client.post(
        reverse('keel_accounts:send_invitation'),
        {**payload, 'acknowledge_existing': '1', 'signed_diff': signed},
        follow=follow,
    )


@pytest.fixture
def org_with_subs(db):
    from keel.accounts.models import Organization, OrganizationProductSubscription

    today = timezone.now().date()
    org = Organization.objects.create(slug='full-org', name='Full Co')
    for code in ('harbor', 'beacon', 'bounty'):
        OrganizationProductSubscription.objects.create(
            organization=org, product=code, is_active=True, started_at=today,
        )
    return org


@pytest.fixture
def admin_user(org_with_subs):
    from keel.accounts.models import KeelUser, ProductAccess

    admin = KeelUser.objects.create_user(
        username='org-admin', email='admin@org.com',
        password='x', organization=org_with_subs,
    )
    # Grant system_admin so ``can_grant_admin_roles`` returns True and
    # protected roles like ``agency_admin`` are grantable.
    ProductAccess.objects.create(
        user=admin, product='harbor', role='system_admin', is_active=True,
    )
    return admin


@pytest.fixture
def existing_user(org_with_subs):
    """Existing KeelUser with one active ProductAccess(harbor, reviewer)."""
    from keel.accounts.models import KeelUser, ProductAccess

    user = KeelUser.objects.create_user(
        username='preexisting', email='existing@example.com',
        password='x', organization=org_with_subs,
    )
    ProductAccess.objects.create(
        user=user, product='harbor', role='reviewer', is_active=True,
    )
    return user


# ---------------------------------------------------------------------------
# Diff builder unit
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_build_existing_user_diff_classifies_each_kind(existing_user):
    from keel.accounts.models import ProductAccess
    from keel.accounts.views import _build_existing_user_diff

    # Add an inactive beacon row so we can test the 'reactivate' branch.
    ProductAccess.objects.create(
        user=existing_user, product='beacon', role='analyst', is_active=False,
    )

    rows = _build_existing_user_diff(
        existing_user,
        [
            ('harbor', 'reviewer', False),       # noop (matches fixture)
            ('harbor', 'agency_admin', False),   # role_change
            ('beacon', 'analyst', False),        # reactivate
            ('bounty', 'analyst', False),        # new_access
            ('harbor', 'reviewer', True),        # beta_change
        ],
    )
    kinds = [r['kind'] for r in rows]
    # Note: harbor appears multiple times because the test passes it
    # multiple times. The classifier is per-row, not per-product.
    assert kinds == [
        'noop', 'role_change', 'reactivate', 'new_access', 'beta_change',
    ]


# ---------------------------------------------------------------------------
# View flow
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_first_post_renders_interstitial_without_creating(client, admin_user, existing_user):
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
    })
    assert response.status_code == 200
    assert b'Confirm access update' in response.content
    # No Invitation rows yet, no email sent.
    assert not Invitation.objects.filter(email=existing_user.email).exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_acknowledged_post_creates_and_sends_update_email(client, admin_user, existing_user):
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = _ack_post(client, {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
    })
    assert response.status_code == 302
    inv = Invitation.objects.get(email=existing_user.email, product='harbor')
    assert inv.role == 'agency_admin'
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    # The "update" subject framing — not the "invited you" framing.
    assert 'updated your DockLabs access' in msg.subject
    assert 'invited you to DockLabs' not in msg.subject


@pytest.mark.django_db
def test_acknowledged_post_skips_noop_products(client, admin_user, existing_user):
    """A pure no-op (same role + beta on active row) creates no Invitation row."""
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = _ack_post(client, {
        'email': existing_user.email,
        # harbor: same role as existing → no-op
        # beacon: new access
        'products': ['harbor', 'beacon'],
        'role__harbor': 'reviewer',
        'role__beacon': 'analyst',
    })
    assert response.status_code == 302
    products = list(
        Invitation.objects.filter(email=existing_user.email)
        .values_list('product', flat=True)
    )
    assert products == ['beacon']


@pytest.mark.django_db
def test_new_user_skips_interstitial_and_uses_invitation_email(client, admin_user):
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'brand-new@example.com',
        'products': ['harbor'],
        'role__harbor': 'reviewer',
    })
    assert response.status_code == 302  # straight through to redirect
    assert Invitation.objects.filter(email='brand-new@example.com').count() == 1
    assert len(mail.outbox) == 1
    assert 'invited you to DockLabs' in mail.outbox[0].subject


# ---------------------------------------------------------------------------
# Accept page
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_accept_page_redirects_anonymous_existing_user_to_login(
    client, admin_user, existing_user, org_with_subs,
):
    from keel.accounts.models import Invitation

    inv = Invitation.objects.create(
        email=existing_user.email, product='beacon', role='analyst',
        invited_by=admin_user, organization=org_with_subs,
        expires_at=timezone.now() + timedelta(days=7),
    )
    # No client.force_login → anonymous request.
    response = client.get(f'/invite/{inv.token}/')
    assert response.status_code == 302
    assert '/accounts/login/' in response.url
    assert f'/invite/{inv.token}/' in response.url


@pytest.mark.django_db
def test_accept_page_review_only_for_signed_in_existing_user(
    client, admin_user, existing_user, org_with_subs,
):
    from keel.accounts.models import Invitation

    inv = Invitation.objects.create(
        email=existing_user.email, product='harbor', role='agency_admin',
        invited_by=admin_user, organization=org_with_subs,
        expires_at=timezone.now() + timedelta(days=7),
    )
    client.force_login(existing_user)
    response = client.get(f'/invite/{inv.token}/')
    assert response.status_code == 200
    assert response.context['is_update'] is True
    diff_rows = response.context['diff_rows']
    assert len(diff_rows) == 1
    assert diff_rows[0]['kind'] == 'role_change'
    # New-user form fields must NOT render on the review page.
    assert b'name="password"' not in response.content
    assert b'name="first_name"' not in response.content
    # Review heading is present.
    assert b'Review your access changes' in response.content


# ---------------------------------------------------------------------------
# Edge-case coverage (gap-fill batch — see /ship coverage audit)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_update_email_body_lists_only_surviving_rows(client, admin_user, existing_user):
    """Mixed batch (noop + new): the update email lists only the changed product."""
    client.force_login(admin_user)
    _ack_post(client, {
        'email': existing_user.email,
        'products': ['harbor', 'beacon'],
        'role__harbor': 'reviewer',  # noop — pre-skipped
        'role__beacon': 'analyst',   # new access — survives
    })
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert 'beacon' in body.lower()
    assert 'analyst' in body.lower()
    # Pre-skipped no-op should not appear in the email body.
    assert 'harbor' not in body.lower()


@pytest.mark.django_db
def test_all_noop_acknowledge_creates_nothing(client, admin_user, existing_user):
    """If every product in the batch is a no-op, no rows or email are created."""
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = _ack_post(client, {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'reviewer',  # matches existing → noop
    })
    assert response.status_code == 302
    assert not Invitation.objects.filter(email=existing_user.email).exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_acknowledge_flag_without_existing_user_is_ignored(client, admin_user):
    """Stale ``acknowledge_existing`` from a form replay is silently ignored.

    The new-user path runs and the legacy invitation email is sent — the
    update template is reserved for genuine existing users.
    """
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'no-such-user@example.com',
        'products': ['harbor'],
        'role__harbor': 'reviewer',
        'acknowledge_existing': '1',  # stale flag
    })
    assert response.status_code == 302
    inv = Invitation.objects.get(email='no-such-user@example.com')
    assert inv.role == 'reviewer'
    assert len(mail.outbox) == 1
    assert 'invited you to DockLabs' in mail.outbox[0].subject
    assert 'updated your DockLabs access' not in mail.outbox[0].subject


@pytest.mark.django_db
def test_role_grant_denial_after_acknowledge_creates_nothing(
    client, existing_user, org_with_subs,
):
    """Role-grant gate runs before existing-user detection. Protected roles
    posted by an actor who can't grant them are dropped from ``valid_rows``
    *before* Phase 2, so neither the interstitial nor any Invitation row
    is produced."""
    from keel.accounts.models import KeelUser, ProductAccess, Invitation

    weak_admin = KeelUser.objects.create_user(
        username='weak-admin', email='weak@org.com',
        password='x', organization=org_with_subs,
    )
    # agency_admin role doesn't satisfy can_grant_admin_roles (needs
    # 'system_admin' or 'admin').
    ProductAccess.objects.create(
        user=weak_admin, product='harbor', role='agency_admin', is_active=True,
    )
    client.force_login(weak_admin)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',  # protected, weak_admin can't grant
        'acknowledge_existing': '1',
    })
    assert response.status_code == 302
    assert not Invitation.objects.filter(email=existing_user.email).exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_mismatch_guard_runs_before_existing_user_branch(
    client, existing_user, admin_user, org_with_subs,
):
    """A user logged in as someone else gets the mismatch 403, not the review page."""
    from keel.accounts.models import Invitation, KeelUser

    other = KeelUser.objects.create_user(
        username='other', email='other@example.com',
        password='x', organization=org_with_subs,
    )
    inv = Invitation.objects.create(
        email=existing_user.email, product='harbor', role='agency_admin',
        invited_by=admin_user, organization=org_with_subs,
        expires_at=timezone.now() + timedelta(days=7),
    )
    client.force_login(other)
    response = client.get(f'/invite/{inv.token}/')
    assert response.status_code == 403
    assert b'Review your access changes' not in response.content


@pytest.mark.django_db
def test_beta_downgrade_classified_as_noop(existing_user):
    """Dropping beta status on an existing access falls through to noop.

    ``Invitation.accept`` only flips ``is_beta_tester`` from False to True;
    it never revokes beta. The diff classifier mirrors this contract: a
    request to "set beta off" against an active beta tester is a no-op,
    not a beta_change. Revocation is admin-driven, not invitation-driven.
    """
    from keel.accounts.models import ProductAccess
    from keel.accounts.views import _build_existing_user_diff

    ProductAccess.objects.filter(
        user=existing_user, product='harbor',
    ).update(is_beta_tester=True)
    rows = _build_existing_user_diff(
        existing_user,
        [('harbor', 'reviewer', False)],  # same role, drop beta
    )
    assert rows[0]['kind'] == 'noop'


@pytest.mark.django_db
def test_acknowledged_post_emits_skipped_noops_message(
    client, admin_user, existing_user,
):
    """Pre-skipped no-op products surface in the messages framework."""
    from django.contrib.messages import get_messages

    client.force_login(admin_user)
    response = _ack_post(client, {
        'email': existing_user.email,
        'products': ['harbor', 'beacon'],
        'role__harbor': 'reviewer',  # noop
        'role__beacon': 'analyst',   # survives
        '_follow': True,
    })
    msgs = [str(m) for m in get_messages(response.wsgi_request)]
    assert any('Skipped' in m and 'harbor' in m for m in msgs)


@pytest.mark.django_db
def test_multi_product_interstitial_shows_all_rows(
    client, admin_user, existing_user,
):
    """Multi-product interstitial renders every diff row and round-trips
    each product's hidden field on the confirm form."""
    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor', 'beacon'],
        'role__harbor': 'agency_admin',  # role_change
        'role__beacon': 'analyst',       # new_access
    })
    assert response.status_code == 200
    diff_rows = response.context['diff_rows']
    kinds = [r['kind'] for r in diff_rows]
    assert 'role_change' in kinds
    assert 'new_access' in kinds
    assert b'name="products" value="harbor"' in response.content
    assert b'name="products" value="beacon"' in response.content


@pytest.mark.django_db
def test_interstitial_form_preserves_beta_field(
    client, admin_user, existing_user,
):
    """Beta hidden field round-trips: interstitial → ack POST keeps beta=1."""
    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['beacon'],
        'role__beacon': 'analyst',
        'beta__beacon': '1',
    })
    assert response.status_code == 200
    assert b'name="beta__beacon"' in response.content


@pytest.mark.django_db
def test_review_page_handles_multi_product_batch(
    client, admin_user, existing_user, org_with_subs,
):
    """Existing user with a multi-product batch invitation sees every product
    in the diff_rows on the review-only accept page."""
    import uuid
    from keel.accounts.models import Invitation

    batch = uuid.uuid4()
    expires = timezone.now() + timedelta(days=7)
    inv1 = Invitation.objects.create(
        email=existing_user.email, product='harbor', role='agency_admin',
        invited_by=admin_user, organization=org_with_subs,
        expires_at=expires, batch_id=batch,
    )
    Invitation.objects.create(
        email=existing_user.email, product='beacon', role='analyst',
        invited_by=admin_user, organization=org_with_subs,
        expires_at=expires, batch_id=batch,
    )
    client.force_login(existing_user)
    response = client.get(f'/invite/{inv1.token}/')
    assert response.status_code == 200
    assert response.context['is_update'] is True
    diff_rows = response.context['diff_rows']
    assert len(diff_rows) == 2
    products = {r['product'] for r in diff_rows}
    assert products == {'harbor', 'beacon'}


@pytest.mark.django_db
def test_update_email_body_contains_change_labels(
    client, admin_user, existing_user,
):
    """Update email body renders the change_summary loop with old + new role."""
    client.force_login(admin_user)
    _ack_post(client, {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',  # role_change from existing 'reviewer'
    })
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    # change_label is "reviewer → agency_admin"; both endpoints must appear.
    assert 'reviewer' in body
    assert 'agency_admin' in body


@pytest.mark.django_db
def test_existing_user_lookup_scoped_to_target_org_for_non_superuser(
    client, admin_user, org_with_subs,
):
    """Email-enumeration defense: a non-superuser admin probing an email
    that belongs to a user in a DIFFERENT org gets the new-user flow,
    not the interstitial. This prevents cross-org user enumeration.
    """
    from keel.accounts.models import (
        Invitation, KeelUser, Organization, OrganizationProductSubscription,
    )

    # Cross-org user lives in a separate organization the admin doesn't act for.
    other_org = Organization.objects.create(slug='other-org', name='Other Org')
    KeelUser.objects.create_user(
        username='cross-org-user',
        email='cross-org@example.com',
        password='x',
        organization=other_org,
    )

    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'cross-org@example.com',
        'products': ['harbor'],
        'role__harbor': 'reviewer',
    })
    # No interstitial — email enumeration was scoped to admin's org and
    # found nothing, so the new-user path runs.
    assert response.status_code == 302
    inv = Invitation.objects.get(email='cross-org@example.com')
    assert inv.role == 'reviewer'
    assert len(mail.outbox) == 1
    assert 'invited you to DockLabs' in mail.outbox[0].subject


@pytest.mark.django_db
def test_existing_user_lookup_unscoped_for_superuser(
    client, org_with_subs,
):
    """Superusers (dokadmin) keep cross-org lookup so suite-wide admin
    operations still work — their cross-org reach is audited separately."""
    from keel.accounts.models import (
        KeelUser, Organization, OrganizationProductSubscription,
    )

    # Cross-org user
    other_org = Organization.objects.create(slug='other-org', name='Other Org')
    KeelUser.objects.create_user(
        username='cross-org-user',
        email='cross-org@example.com',
        password='x',
        organization=other_org,
    )

    superuser = KeelUser.objects.create_superuser(
        username='dokadmin', email='dokadmin@example.com',
        password='x', organization=org_with_subs,
    )
    client.force_login(superuser)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': 'cross-org@example.com',
        'products': ['harbor'],
        'role__harbor': 'reviewer',
    })
    # Superuser sees the interstitial because cross-org lookup is unscoped.
    assert response.status_code == 200
    assert b'Confirm access update' in response.content


@pytest.mark.django_db
def test_unsigned_acknowledge_rerenders_interstitial(client, admin_user, existing_user):
    """A re-POST claiming acknowledge_existing=1 without a signed_diff
    is rejected — the interstitial re-renders so the admin must consent
    via the proper two-step flow."""
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
        'acknowledge_existing': '1',  # no signed_diff
    })
    # Re-renders the interstitial, no Invitation row, no email.
    assert response.status_code == 200
    assert b'Confirm access update' in response.content
    assert response.context['drift_warning'] is True
    assert not Invitation.objects.filter(email=existing_user.email).exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_tampered_signature_rerenders_interstitial(client, admin_user, existing_user):
    """A re-POST with a corrupted signed_diff is rejected (BadSignature)."""
    from keel.accounts.models import Invitation

    client.force_login(admin_user)
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
        'acknowledge_existing': '1',
        'signed_diff': 'not-a-real-signature.payload.suffix',
    })
    assert response.status_code == 200
    assert response.context['drift_warning'] is True
    assert not Invitation.objects.filter(email=existing_user.email).exists()


@pytest.mark.django_db
def test_drift_between_phases_rerenders_interstitial(
    client, admin_user, existing_user,
):
    """If the target's role changes between phase-1 render and phase-2
    click, the signed payload no longer matches current state and the
    interstitial re-renders with the drift warning."""
    from keel.accounts.models import Invitation, ProductAccess

    client.force_login(admin_user)
    # Phase 1 — admin sees diff "reviewer → agency_admin".
    phase1 = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
    })
    assert phase1.status_code == 200
    signed = phase1.context['signed_diff']

    # Drift: another admin changes existing_user's harbor role.
    ProductAccess.objects.filter(
        user=existing_user, product='harbor',
    ).update(role='reviewer')  # no change — but let's actually change
    ProductAccess.objects.filter(
        user=existing_user, product='harbor',
    ).update(role='applicant')

    # Phase 2 — same signed_diff, but DB state differs now.
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
        'acknowledge_existing': '1',
        'signed_diff': signed,
    })
    assert response.status_code == 200
    assert response.context['drift_warning'] is True
    assert not Invitation.objects.filter(email=existing_user.email).exists()


@pytest.mark.django_db
def test_tampered_email_in_phase2_rerenders_interstitial(
    client, admin_user, existing_user, org_with_subs,
):
    """Admin DOM-tampers with the hidden email field between phase-1 and
    phase-2. The signed_diff was generated for existing_user.email but
    the re-POST claims a different email — the canonical re-derivation
    won't match the signature and the interstitial re-renders.

    Critically, the email actually sent (if any) goes to existing_user.email,
    not the tampered email — the signature pins the recipient.
    """
    from keel.accounts.models import KeelUser, Invitation

    # Create a second existing user we'll try to "swap" to.
    other = KeelUser.objects.create_user(
        username='swap-target', email='swap-target@example.com',
        password='x', organization=org_with_subs,
    )
    client.force_login(admin_user)
    # Phase 1 — diff signed for existing_user.email.
    phase1 = client.post(reverse('keel_accounts:send_invitation'), {
        'email': existing_user.email,
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
    })
    signed_for_existing = phase1.context['signed_diff']

    # Phase 2 — admin tampers the hidden email field.
    response = client.post(reverse('keel_accounts:send_invitation'), {
        'email': other.email,  # swapped!
        'products': ['harbor'],
        'role__harbor': 'agency_admin',
        'acknowledge_existing': '1',
        'signed_diff': signed_for_existing,  # signature for THE OTHER email
    })
    # Re-renders interstitial; no Invitation created for either email.
    assert response.status_code == 200
    assert response.context['drift_warning'] is True
    assert not Invitation.objects.filter(email=other.email).exists()
    assert not Invitation.objects.filter(email=existing_user.email).exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_role_change_with_beta_combined_in_label(existing_user):
    """When role and beta both flip at once, the diff label surfaces both."""
    from keel.accounts.models import ProductAccess
    from keel.accounts.views import _build_existing_user_diff

    # Existing user is on harbor as 'reviewer' with beta off.
    rows = _build_existing_user_diff(
        existing_user,
        [('harbor', 'agency_admin', True)],  # role change AND beta on
    )
    assert rows[0]['kind'] == 'role_change'
    assert '+beta' in rows[0]['change_label']
    assert 'reviewer' in rows[0]['change_label']
    assert 'agency_admin' in rows[0]['change_label']


@pytest.mark.django_db
def test_anonymous_redirect_preserves_token(
    client, admin_user, existing_user, org_with_subs,
):
    """The login URL after the anonymous redirect carries ?next=/invite/<token>/
    so signing in lands the user back on the review page."""
    from keel.accounts.models import Invitation

    inv = Invitation.objects.create(
        email=existing_user.email, product='harbor', role='agency_admin',
        invited_by=admin_user, organization=org_with_subs,
        expires_at=timezone.now() + timedelta(days=7),
    )
    response = client.get(f'/invite/{inv.token}/')
    assert response.status_code == 302
    assert f'next=/invite/{inv.token}/' in response.url
