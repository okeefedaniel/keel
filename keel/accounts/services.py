"""Org-aware service layer for keel.accounts.

Pulled into a module separate from models.py so the reconcile
function isn't subject to ``models.py``'s import-time circular
constraints (the ``KeelUser.save`` hook imports it lazily).
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# Roles a non-system_admin admin (e.g. agency_admin) cannot grant. Centralized
# here so the invitation matrix renderer, the POST validator, and any future
# role-grant surface (programmatic API, future bulk-import tools) read from
# one allowlist. Adding a new admin-tier role to a product means adding it
# here too.
PROTECTED_ADMIN_ROLES = frozenset({
    'system_admin',
    'agency_admin',
    'admin',
    'helm_admin',
    'yeoman_admin',
    'purser_admin',
})


def can_grant_admin_roles(actor) -> bool:
    """Return True when ``actor`` can grant protected admin-tier roles.

    System admins (and superusers) can grant any role. Agency admins can
    grant operator-tier roles within their org but NOT another admin-tier
    role — that escalation path stays with system admins. The check is
    intentionally permissive on superuser and on the legacy ``admin`` Keel
    role so this rollout doesn't strip rights from existing dokadmin-style
    accounts.
    """
    if getattr(actor, 'is_superuser', False):
        return True
    # Read role across ALL ProductAccess rows: an actor may hold
    # system_admin in Keel itself even if they're not currently
    # browsing a Keel-aware page. The invitation matrix is a Keel
    # surface, so any system_admin role anywhere in the user's
    # ProductAccess set is sufficient.
    from keel.accounts.models import ProductAccess
    return ProductAccess.objects.filter(
        user=actor,
        role__in=('system_admin', 'admin'),
        is_active=True,
    ).exists()


def available_grantable_roles(actor, product_code: str) -> list[tuple[str, str]]:
    """Return the role choices ``actor`` is allowed to grant for ``product_code``.

    System admins / superusers see the full role list for the product.
    Agency admins (and any other non-system admin) see the list minus
    ``PROTECTED_ADMIN_ROLES`` — so an agency_admin cannot self-escalate
    or peer-escalate via the invitation matrix.

    Returns the same `(slug, label)` tuple shape as
    ``get_product_roles(product_code)`` so it slots into existing
    template / form choice rendering without further wrapping.
    """
    from keel.accounts.models import get_product_roles
    full = list(get_product_roles(product_code) or [])
    if can_grant_admin_roles(actor):
        return full
    return [(slug, label) for slug, label in full if slug not in PROTECTED_ADMIN_ROLES]


def reconcile_user_product_access(user, force_logout: bool = True) -> int:
    """Deactivate ProductAccess rows the user's org no longer subscribes to.

    Called from ``KeelUser.save`` whenever ``organization`` changes
    (the snapshot pattern in ``KeelUser.__init__`` detects the change),
    and from the ``reconcile_org_product_access`` management command
    on a daily cron.

    Closes CSO finding S1 (privilege bleed on org reassignment): a user
    moved from an org with the full suite to an org with only Bounty
    keeps their existing ProductAccess rows otherwise; this function
    sweeps them.

    Closes CSO finding S2 (stale JWT) when ``force_logout=True``:
    bumping ``user.last_logout_at`` invalidates any active per-product
    sessions on the next request via ``SessionFreshnessMiddleware``.

    Returns the count of ProductAccess rows deactivated. Returns 0
    immediately for cross-org superusers (no org → no constraint to
    enforce).
    """
    if user.is_superuser or user.organization_id is None:
        return 0

    # Imported here to avoid the import-time circular: services.py is
    # imported from models.py via KeelUser.save's lazy local import.
    from keel.accounts.models import (
        Organization,
        OrganizationProductSubscription,
        ProductAccess,
    )

    # Resolve subscriptions by organization_id directly, bypassing the
    # ForwardManyToOneDescriptor on user.organization. This avoids
    # ``Organization.DoesNotExist`` raising during transactional test
    # setUp / tearDown windows where the FK row may be temporarily
    # absent (e.g. test fixtures that reuse a user across cases, or
    # a partially-migrated CI database where 0011 rolled back). When
    # the org row truly doesn't exist, we no-op rather than crash.
    if not Organization.objects.filter(pk=user.organization_id).exists():
        logger.warning(
            'reconcile_user_product_access: user=%s has organization_id=%s '
            'but the row was not found; skipping reconcile',
            user.pk, user.organization_id,
        )
        return 0
    subscribed = OrganizationProductSubscription.active_product_codes(
        user.organization_id
    )

    with transaction.atomic():
        deactivated_qs = (
            ProductAccess.objects
            .filter(user=user, is_active=True)
            .exclude(product__in=subscribed)
        )
        # Snapshot for logging BEFORE the update, so we can write a
        # readable line if something cares to audit which products
        # got revoked.
        revoked_products = list(
            deactivated_qs.values_list('product', flat=True)
        )
        deactivated = deactivated_qs.update(is_active=False)

        if deactivated and force_logout:
            # Reuse the existing last_logout_at infrastructure
            # (deployed across all 9 products in keel >= 0.20.0)
            # rather than introducing a new column. SessionFreshness
            # middleware will see the bumped timestamp and tear down
            # stale per-product sessions on the next request.
            user.last_logout_at = timezone.now()
            # update_fields prevents triggering KeelUser.save's own
            # org-change detection (organization didn't change here).
            user.__class__.objects.filter(pk=user.pk).update(
                last_logout_at=user.last_logout_at,
            )

    if deactivated:
        logger.info(
            'reconcile_user_product_access: revoked %d ProductAccess '
            'rows for user=%s org=%s; revoked_products=%s force_logout=%s',
            deactivated,
            user.pk,
            user.organization_id,
            revoked_products,
            force_logout,
        )

    return deactivated


def rename_user(user, new_username: str, *, actor=None) -> str:
    """Rename ``user`` to ``new_username`` and re-key SSO linkage.

    A username rename has four side effects that MUST happen atomically:

    1. ``KeelUser.username`` is updated.
    2. Every linked ``allauth.socialaccount.SocialAccount.uid`` for the
       user is rewritten — allauth uses ``uid`` as the linking key for
       OIDC roundtrips, and Keel's ``KeelSocialAccountAdapter.populate_user``
       sets ``user.username = preferred_username`` from the JWT on every
       login. If ``uid`` and ``KeelUser.username`` drift, the next sign-in
       creates a duplicate user (``dan`` / ``dan2`` zombie pattern).
    3. ``user.last_logout_at`` is bumped so ``SessionFreshnessMiddleware``
       (deployed across all 9 products in keel ≥ 0.20.0) tears down per-
       product sessions on the next request and the user re-handshakes
       with the new ``preferred_username`` in the JWT.
    4. An ``AuditLog`` row is written for the security trail (admins
       reviewing access activity should see "username changed" alongside
       password resets and email changes).

    Parameters
    ----------
    user
        The ``KeelUser`` being renamed. Required.
    new_username
        The candidate. MUST already have passed ``validate_username_format``
        and a uniqueness check at the form layer — this function re-checks
        uniqueness inside the transaction (race window between live-check
        and submit) and raises ``ValueError`` on collision rather than
        silently overwriting.
    actor
        The user performing the rename. Defaults to ``user`` for self-
        service renames; admin-driven renames pass the admin as ``actor``
        so the audit row identifies who made the change.

    Returns
    -------
    str
        The new username (lowercased, stripped) — useful for the calling
        view to message the user with the canonical form.

    Raises
    ------
    ValueError
        On format failure, reservation, self-rename to current value, or
        uniqueness collision detected inside the atomic block.
    """
    from django.db import transaction
    from keel.accounts.forms import validate_username_format
    from keel.accounts.models import KeelUser

    candidate = (new_username or '').strip().lower()
    err = validate_username_format(candidate)
    if err is not None:
        raise ValueError(f'username_validation: {err}')
    if candidate == user.username:
        raise ValueError('username_validation: unchanged')

    old_username = user.username
    actor = actor or user

    with transaction.atomic():
        # Lock the row to keep two simultaneous renames from racing.
        # ``select_for_update`` on the user table is fine — KeelUser
        # has a UUID PK so this is a single row lock.
        locked = KeelUser.objects.select_for_update().filter(pk=user.pk).first()
        if locked is None:
            raise ValueError('username_validation: user_not_found')

        # Re-check uniqueness inside the lock. ``__iexact`` matches the
        # form-layer policy — `Dan` and `dan` are the same name.
        if KeelUser.objects.filter(
            username__iexact=candidate,
        ).exclude(pk=user.pk).exists():
            raise ValueError('username_validation: taken')

        locked.username = candidate
        locked.last_logout_at = timezone.now()
        locked.save(update_fields=['username', 'last_logout_at'])

        # Re-key SocialAccount.uid for every Keel-OIDC linkage. Allauth's
        # OIDC provider stores ``preferred_username`` in ``uid`` so the
        # next login matches the same row. Microsoft Entra accounts use
        # the OID/sub as ``uid`` and aren't affected by username — we
        # filter by provider to skip them.
        try:
            from allauth.socialaccount.models import SocialAccount
            SocialAccount.objects.filter(
                user_id=user.pk,
                provider='keel',
            ).update(uid=candidate)
        except Exception:
            # allauth not installed (Keel-only deployments where the IdP
            # itself isn't an OIDC client of anything) — nothing to re-key.
            logger.debug('rename_user: allauth not present; skipping uid update')

        # Audit log. Wrapped in try/except so a missing or differently-
        # configured AuditLog model doesn't block the rename — the rename
        # itself is the operationally important part. Each product carries
        # its own concrete AuditLog table; here we write into Keel's.
        try:
            from django.apps import apps
            from django.conf import settings as django_settings
            audit_label = getattr(
                django_settings, 'KEEL_AUDIT_LOG_MODEL', None,
            )
            if audit_label:
                AuditLog = apps.get_model(audit_label)
                AuditLog.objects.create(
                    user=actor,
                    action='username_change',
                    entity_type='KeelUser',
                    entity_id=str(user.pk),
                    changes={
                        'old_username': old_username,
                        'new_username': candidate,
                        'self_service': actor.pk == user.pk,
                    },
                )
        except Exception:
            logger.exception(
                'rename_user: audit log write failed for user=%s; rename succeeded',
                user.pk,
            )

    # Mirror onto the in-memory object the caller passed in so subsequent
    # template rendering reads the new value without a refetch.
    user.username = candidate
    user.last_logout_at = locked.last_logout_at

    logger.info(
        'rename_user: user=%s renamed %r → %r by actor=%s',
        user.pk, old_username, candidate, actor.pk,
    )
    return candidate


# ---------------------------------------------------------------------------
# Avatar pipeline — used by ProfilePanel POST and admin tools
# ---------------------------------------------------------------------------

# Browser-uploaded constraints. Larger than the post-process size on
# purpose: a 5 MB JPEG resizes down to ~30 KB WebP at 512×512 quality 85,
# but rejecting before the resize lets us refuse abusive uploads early.
AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_ALLOWED_CONTENT_TYPES = frozenset({
    'image/jpeg', 'image/png', 'image/webp',
})
AVATAR_OUTPUT_SIZE = 512  # square WebP edge length
AVATAR_OUTPUT_QUALITY = 85


def _process_avatar_bytes(raw: bytes) -> tuple[bytes, str]:
    """Validate, resize, strip EXIF, re-encode → ``(bytes, sha256_hex)``.

    Pillow notes:

    - ``ImageOps.exif_transpose`` honors EXIF orientation BEFORE we strip
      metadata, so portrait phone photos render upright. Without this,
      iPhone-shot avatars come out rotated 90° because the underlying
      pixels are landscape and the orientation tag would have rotated
      them.
    - ``Image.convert('RGB')`` flattens any alpha channel, drops palette
      modes (P, L), and gives WebP a consistent color space. WebP would
      otherwise emit lossy-with-alpha which is bigger and looks worse on
      the typical white-background avatar.
    - ``ImageOps.fit`` is cover-crop (resize so the smallest dimension
      equals 512, then center-crop the longer axis). Equivalent to
      ``object-fit: cover`` in CSS.
    - The default WebP encoder strips EXIF; we never pass ``exif=`` to
      ``save()`` so metadata never makes it through.

    Raises ``ValueError`` on any decode failure or unsupported format —
    the calling view re-shapes that into a user-facing form error.
    """
    import hashlib
    import io

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f'avatar_invalid: cannot decode image ({exc})')

    # Pillow lowercases the format identifier. JPEG → 'JPEG', PNG → 'PNG',
    # WebP → 'WEBP'. Reject anything outside our allowlist (animated GIF,
    # TIFF, BMP, etc.) — even though browsers might accept them, our own
    # AVATAR_ALLOWED_CONTENT_TYPES already gated this on the way in;
    # this is defense-in-depth in case someone POSTed a renamed file.
    fmt = (img.format or '').upper()
    if fmt not in {'JPEG', 'PNG', 'WEBP'}:
        raise ValueError(f'avatar_invalid: unsupported format {fmt!r}')

    img = ImageOps.exif_transpose(img)
    img = img.convert('RGB')
    img = ImageOps.fit(
        img,
        (AVATAR_OUTPUT_SIZE, AVATAR_OUTPUT_SIZE),
        method=Image.Resampling.LANCZOS,
    )

    out = io.BytesIO()
    # ``method=6`` is Pillow's slowest/best-compression WebP setting —
    # avatars are written once and read many times, so the extra ~10 ms
    # of CPU at upload time is repaid in CDN egress savings forever.
    img.save(out, format='WEBP', quality=AVATAR_OUTPUT_QUALITY, method=6)
    body = out.getvalue()
    digest = hashlib.sha256(body).hexdigest()
    return body, digest


def set_avatar(user, uploaded_file, *, actor=None) -> str:
    """Validate + process + persist a new avatar for ``user``.

    Returns the storage key (path within the bucket / FS) of the saved
    file so callers can log it. Raises ``ValueError`` on validation
    failure with one of these codes (suitable for direct form-error
    display after stripping the prefix):

    - ``avatar_invalid: too_large``
    - ``avatar_invalid: bad_content_type``
    - ``avatar_invalid: cannot decode image (...)``
    - ``avatar_invalid: unsupported format ...``

    The key shape is ``avatars/{user_id}/{sha256_hex}.webp``. Content-
    addressing means re-uploading the same image is idempotent and the
    URL changes whenever the image changes — CDN caching is automatic
    and we never need explicit invalidation.

    Side effects:
    - Old avatar file (if any) is deleted from storage AFTER the new
      one is saved, so a concurrent reader never sees a 404.
    - ``user.avatar`` is updated and ``user.save(update_fields=['avatar'])``
      is called.
    - ``AuditLog`` entry written when ``KEEL_AUDIT_LOG_MODEL`` is set.
    """
    actor = actor or user

    # Size check — read once. Django's UploadedFile.size is set from
    # Content-Length / spooled tempfile size, no actual decode yet.
    size = getattr(uploaded_file, 'size', None) or 0
    if size > AVATAR_MAX_BYTES:
        raise ValueError('avatar_invalid: too_large')

    content_type = (
        getattr(uploaded_file, 'content_type', '') or ''
    ).split(';')[0].strip().lower()
    if content_type not in AVATAR_ALLOWED_CONTENT_TYPES:
        raise ValueError('avatar_invalid: bad_content_type')

    raw = uploaded_file.read()
    body, digest = _process_avatar_bytes(raw)

    from django.core.files.base import ContentFile
    from keel.accounts.models import KeelUser

    # Field's ``upload_to='avatars/'`` adds the prefix; we pass just the
    # per-user/per-content portion. Resulting key is
    # ``avatars/{user_id}/{sha256_hex}.webp``.
    new_relative = f'{user.pk}/{digest}.webp'

    # Capture the previous file name (if any) so we can delete it
    # after the new one is in place. Pulling .name from the FileField
    # lazy-evaluates to '' when no file is attached.
    old_name = user.avatar.name if user.avatar else ''

    # Write the file at exactly ``full_key`` without the random
    # collision-avoidance suffix that ``Storage.save`` would add on
    # FileSystemStorage. Strategy depends on the backend:
    #
    # - S3Storage runs with ``file_overwrite=True`` — ``save()`` writes
    #   straight through, idempotent for repeated uploads of the same
    #   image. We don't call ``storage.exists()`` because that requires
    #   ``s3:GetObject`` / HeadObject permission, and the writer IAM
    #   role is intentionally write-only (PutObject + DeleteObject).
    #
    # - FileSystemStorage doesn't honor ``file_overwrite``; ``save()``
    #   would suffix the name. Delete-then-save reaches the same
    #   deterministic key. ``delete()`` is a no-op on missing files
    #   under FSS, so the try/except is just defensive.
    full_key = f'avatars/{new_relative}'
    storage = user.avatar.storage
    if not getattr(storage, 'file_overwrite', False):
        try:
            storage.delete(full_key)
        except Exception:
            pass
    saved_name = storage.save(full_key, ContentFile(body))
    user.avatar.name = saved_name
    KeelUser.objects.filter(pk=user.pk).update(avatar=saved_name)

    # Delete the old file (best-effort). Do this AFTER the new file is
    # committed so a CDN that's already cached the old URL gets a fresh
    # 200 from the new path; the old URL goes 404 only after the cache
    # expires, which is fine because nothing should still be linking to
    # it. Skip when the old key happens to match the new one (idempotent
    # re-upload of the same image).
    if old_name and old_name != user.avatar.name:
        try:
            user.avatar.storage.delete(old_name)
        except Exception:
            logger.warning(
                'set_avatar: failed to delete old avatar %r for user=%s',
                old_name, user.pk, exc_info=True,
            )

    # Audit log — same defensive try/except as rename_user.
    try:
        from django.apps import apps
        from django.conf import settings as django_settings
        audit_label = getattr(
            django_settings, 'KEEL_AUDIT_LOG_MODEL', None,
        )
        if audit_label:
            AuditLog = apps.get_model(audit_label)
            AuditLog.objects.create(
                user=actor,
                action='avatar_change',
                entity_type='KeelUser',
                entity_id=str(user.pk),
                changes={
                    'old_key': old_name or None,
                    'new_key': user.avatar.name,
                    'self_service': actor.pk == user.pk,
                },
            )
    except Exception:
        logger.exception(
            'set_avatar: audit log write failed for user=%s; upload succeeded',
            user.pk,
        )

    logger.info(
        'set_avatar: user=%s key=%s size=%d',
        user.pk, user.avatar.name, len(body),
    )
    return user.avatar.name


def clear_avatar(user, *, actor=None) -> bool:
    """Delete the user's uploaded avatar; revert to fallback rendering.

    Returns ``True`` when there was something to delete, ``False`` when
    the user had no avatar set. Always safe to call.
    """
    actor = actor or user
    if not user.avatar:
        return False

    old_name = user.avatar.name
    try:
        user.avatar.storage.delete(old_name)
    except Exception:
        logger.warning(
            'clear_avatar: storage delete failed for user=%s key=%s',
            user.pk, old_name, exc_info=True,
        )

    user.avatar = None
    user.save(update_fields=['avatar'])

    try:
        from django.apps import apps
        from django.conf import settings as django_settings
        audit_label = getattr(
            django_settings, 'KEEL_AUDIT_LOG_MODEL', None,
        )
        if audit_label:
            AuditLog = apps.get_model(audit_label)
            AuditLog.objects.create(
                user=actor,
                action='avatar_change',
                entity_type='KeelUser',
                entity_id=str(user.pk),
                changes={'old_key': old_name, 'new_key': None,
                         'self_service': actor.pk == user.pk},
            )
    except Exception:
        logger.exception('clear_avatar: audit log write failed user=%s', user.pk)

    return True


# ---------------------------------------------------------------------------
# Email change pipeline
# ---------------------------------------------------------------------------
def _allauth_available() -> bool:
    """True when this deployment has django-allauth installed.

    Products use allauth as their OIDC client; Keel itself does NOT
    (Keel uses Django native auth). We dispatch the email change flow
    on this so Keel-side requests land on our native PendingEmailChange
    flow and product-side requests reuse allauth's existing
    EmailAddress.add_email confirmation pipeline.
    """
    try:
        import allauth.account.models  # noqa: F401
        return True
    except Exception:
        return False


def request_email_change(user, new_email: str, request=None) -> dict:
    """Kick off an email-address change for *user*.

    Dispatch:

    - allauth installed → ``EmailAddress.objects.add_email(...)``: the
      allauth machinery sends its own confirmation email and rotates
      the address only when the user clicks. No keel-side row written.
    - allauth absent → ``PendingEmailChange.issue(...)`` + a templated
      email built from ``keel.accounts.email_change`` templates.

    Returns a small dict so callers can log without re-reading state:

    .. code-block:: python

        {'mode': 'allauth' | 'native',
         'pending': PendingEmailChange | None,
         'new_email': str}

    Raises ``ValueError`` (with structured prefixes) on validation
    failure that the form layer didn't catch.
    """
    candidate = (new_email or '').strip().lower()
    if not candidate:
        raise ValueError('email_invalid: empty')
    if candidate == (user.email or '').lower():
        raise ValueError('email_invalid: unchanged')

    if _allauth_available():
        # The product side. Allauth's add_email handles confirmation
        # email rendering, the click-to-confirm view, and rotating
        # ``user.email`` once verified — all already deployed in every
        # product.
        from allauth.account.models import EmailAddress
        EmailAddress.objects.add_email(
            request, user, candidate, confirm=True,
        )
        logger.info(
            'request_email_change: user=%s allauth handed off to %s',
            user.pk, candidate,
        )
        return {'mode': 'allauth', 'pending': None, 'new_email': candidate}

    # The Keel-IdP side. No allauth — write a PendingEmailChange row,
    # render a token URL, send the mail through Keel's configured email
    # backend.
    from keel.accounts.models import PendingEmailChange

    pending = PendingEmailChange.issue(user, candidate)
    _send_email_change_confirmation(user, pending, request)
    logger.info(
        'request_email_change: user=%s native pending=%s → %s',
        user.pk, pending.pk, candidate,
    )
    return {'mode': 'native', 'pending': pending, 'new_email': candidate}


def _send_email_change_confirmation(user, pending, request) -> None:
    """Build and send the keel-native confirmation email.

    Uses Django's standard ``send_mail`` with templates rendered via
    ``render_to_string`` so customers can override the look/voice by
    shadowing ``accounts/email_change/{subject,body,body_html}.txt``
    in their own template directory. The plain-text body is the canonical
    one — HTML is a courtesy.
    """
    from django.conf import settings as django_settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.urls import reverse

    # Build the absolute URL. ``request`` may be None when we're called
    # from a management command or shell; fall back to the configured
    # issuer host so we can still produce a working link.
    path = reverse('keel_accounts:confirm_email_change',
                   kwargs={'token': pending.token})
    if request is not None:
        confirm_url = request.build_absolute_uri(path)
    else:
        host = (
            getattr(django_settings, 'KEEL_OIDC_ISSUER', '')
            or getattr(django_settings, 'SITE_URL', '')
        ).rstrip('/')
        confirm_url = f'{host}{path}' if host else path

    ctx = {
        'user': user,
        'new_email': pending.new_email,
        'confirm_url': confirm_url,
        'expires_at': pending.expires_at,
        'ttl_hours': int(
            (pending.expires_at - pending.created_at).total_seconds() // 3600
        ),
        'site_name': getattr(django_settings, 'SITE_NAME', 'DockLabs'),
    }

    subject = render_to_string(
        'accounts/email_change/subject.txt', ctx,
    ).strip().replace('\n', ' ')
    text_body = render_to_string('accounts/email_change/body.txt', ctx)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(
            django_settings, 'DEFAULT_FROM_EMAIL',
            'DockLabs <info@docklabs.ai>',
        ),
        to=[pending.new_email],
    )
    try:
        html_body = render_to_string('accounts/email_change/body.html', ctx)
        msg.attach_alternative(html_body, 'text/html')
    except Exception:
        # HTML template is optional; keep the plain-text path working.
        pass
    msg.send(fail_silently=False)


def confirm_email_change(token: str) -> dict:
    """Apply a pending email change identified by *token*.

    Returns:

    .. code-block:: python

        {'ok': bool, 'reason': str | None,
         'user': KeelUser | None, 'old_email': str, 'new_email': str}

    Reason codes when ``ok=False``: ``not_found``, ``expired``,
    ``already_confirmed``, ``email_taken`` (someone else grabbed the
    address between request and click).

    Side effects on success:
    - ``user.email`` is updated.
    - ``user.last_logout_at`` is bumped so other-product sessions invalidate.
    - The PendingEmailChange row is marked confirmed (kept for audit).
    - An ``AuditLog`` row is written.
    """
    from django.db import transaction
    from keel.accounts.models import KeelUser, PendingEmailChange

    pending = PendingEmailChange.objects.filter(token=token).first()
    if pending is None:
        return {'ok': False, 'reason': 'not_found',
                'user': None, 'old_email': '', 'new_email': ''}
    if pending.is_consumed():
        return {'ok': False, 'reason': 'already_confirmed',
                'user': pending.user, 'old_email': pending.user.email,
                'new_email': pending.new_email}
    if pending.is_expired():
        return {'ok': False, 'reason': 'expired',
                'user': pending.user, 'old_email': pending.user.email,
                'new_email': pending.new_email}

    user = pending.user
    old_email = user.email or ''
    new_email = pending.new_email

    with transaction.atomic():
        # Re-check uniqueness inside the transaction. Race window:
        # someone else could have grabbed the address in the time
        # between request_email_change and confirm.
        if KeelUser.objects.filter(
            email__iexact=new_email,
        ).exclude(pk=user.pk).exists():
            return {'ok': False, 'reason': 'email_taken',
                    'user': user, 'old_email': old_email,
                    'new_email': new_email}

        user.email = new_email
        user.last_logout_at = timezone.now()
        user.save(update_fields=['email', 'last_logout_at'])

        pending.confirmed_at = timezone.now()
        pending.save(update_fields=['confirmed_at'])

    try:
        from django.apps import apps
        from django.conf import settings as django_settings
        audit_label = getattr(django_settings, 'KEEL_AUDIT_LOG_MODEL', None)
        if audit_label:
            AuditLog = apps.get_model(audit_label)
            AuditLog.objects.create(
                user=user,
                action='email_change',
                entity_type='KeelUser',
                entity_id=str(user.pk),
                changes={
                    'old_email': old_email,
                    'new_email': new_email,
                    'self_service': True,
                },
            )
    except Exception:
        logger.exception(
            'confirm_email_change: audit write failed user=%s',
            user.pk,
        )

    logger.info(
        'confirm_email_change: user=%s %r → %r',
        user.pk, old_email, new_email,
    )
    return {'ok': True, 'reason': None, 'user': user,
            'old_email': old_email, 'new_email': new_email}


def reconcile_all_users(*, force_logout: bool = False) -> dict:
    """Sweep every user, reconciling their ProductAccess.

    Called by the ``reconcile_org_product_access`` management command
    (daily cron) so admin actions that bypass ``KeelUser.save`` (raw
    SQL fixes, replication-based bulk imports) still get caught.

    ``force_logout=False`` by default for the cron path so a sweep
    doesn't kick every user out of their session every night. Direct
    org-change reconciliation (via the save hook) does pass
    ``force_logout=True``.

    Returns a small report dict for logging.
    """
    from keel.accounts.models import KeelUser

    total_users = 0
    total_revoked = 0

    qs = KeelUser.objects.filter(
        is_active=True,
        is_superuser=False,
        organization__isnull=False,
    ).select_related('organization')

    for user in qs.iterator():
        total_users += 1
        revoked = reconcile_user_product_access(user, force_logout=force_logout)
        total_revoked += revoked

    logger.info(
        'reconcile_all_users: scanned %d users, revoked %d ProductAccess rows',
        total_users, total_revoked,
    )
    return {
        'users_scanned': total_users,
        'rows_revoked': total_revoked,
    }
