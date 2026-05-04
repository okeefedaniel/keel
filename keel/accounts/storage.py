"""Storage backend selection for KeelUser.avatar.

The avatar field's storage is resolved at access time so that the
deployment topology (S3 vs local filesystem) is decided per-environment
without baking a backend choice into migrations.

Resolution order:

1. ``settings.KEEL_AVATAR_BUCKET`` set → S3 backend via ``django-storages``.
   Optional CDN substitution via ``KEEL_AVATAR_CDN_BASE_URL`` (CloudFront).
2. Otherwise → Django's default ``FileSystemStorage`` (local ``MEDIA_ROOT``).
   This path is for dev and standalone deployments without object storage.

Why a callable (not a settings string)? Django ImageField's ``storage``
parameter accepts either a Storage instance or a zero-arg callable that
returns one; using the callable form means the backend is chosen at
first use, so importing the model doesn't require boto3 / django-storages
to be installed unless the deployment opts into S3.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def avatar_storage():
    """Return the Storage instance to use for ``KeelUser.avatar``.

    Cached on the function object after first call. Safe to invoke from
    a model field's ``storage=`` parameter.
    """
    cached = getattr(avatar_storage, '_cached', None)
    if cached is not None:
        return cached

    from django.conf import settings
    bucket = getattr(settings, 'KEEL_AVATAR_BUCKET', '') or ''

    if not bucket:
        # No bucket configured → local filesystem rooted at MEDIA_ROOT.
        # Avoid the LazyObject ``default_storage`` indirection — that
        # works in production but trips on settings.STORAGES lookup in
        # ad-hoc shells / minimal test envs that don't define STORAGES.
        from django.core.files.storage import FileSystemStorage
        storage = FileSystemStorage()
        avatar_storage._cached = storage
        return storage

    try:
        from storages.backends.s3 import S3Storage
    except ImportError:
        # django-storages isn't installed but a bucket was set. Surface
        # a loud error rather than silently falling back to local —
        # that fallback would write avatars to ephemeral Railway disk
        # while the operator believes they're on S3.
        raise RuntimeError(
            'KEEL_AVATAR_BUCKET is set but django-storages is not '
            'installed. Add `keel[avatars-s3]` to your requirements.'
        )

    # CDN custom domain — strip scheme/trailing-slash since django-storages
    # wants a bare hostname.
    cdn_url = getattr(settings, 'KEEL_AVATAR_CDN_BASE_URL', '') or ''
    custom_domain = (
        cdn_url.replace('https://', '').replace('http://', '').rstrip('/')
        or None
    )

    storage = S3Storage(
        bucket_name=bucket,
        region_name=getattr(settings, 'KEEL_AVATAR_REGION', 'us-east-1'),
        custom_domain=custom_domain,
        # Bucket has ACLs disabled (modern default); don't set per-object
        # ACLs or PutObject calls fail with AccessControlListNotSupported.
        default_acl=None,
        # Public-read bucket → no need to sign URLs.
        querystring_auth=False,
        # We content-address by SHA-256 so collisions on the same key
        # are intentional (idempotent re-upload of the same image). Allow
        # overwrite — a no-op on identical content.
        file_overwrite=True,
    )
    avatar_storage._cached = storage
    return storage
