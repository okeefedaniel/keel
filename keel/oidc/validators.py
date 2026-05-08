"""Custom OAuth2/OIDC validator for Keel.

Adds DockLabs-specific claims to ID tokens issued by Keel:

- ``product_access`` — dict mapping product code to role, e.g.
  ``{"harbor": "program_officer", "beacon": "analyst"}``. Each product's
  ``ProductAccessMiddleware`` reads this claim and uses it instead of
  hitting the database.

- ``email``, ``name``, ``given_name``, ``family_name``, ``preferred_username``
  — standard OIDC profile claims, populated from ``KeelUser``.

- ``is_state_user``, ``agency_abbr`` — DockLabs-specific user attributes
  used by some products' role logic.

This module is import-safe: it does NOT import ``oauth2_provider`` at module
load time. ``django-oauth-toolkit`` is only required on Keel itself (where
this validator is wired up via ``OAUTH2_PROVIDER['OAUTH2_VALIDATOR_CLASS']``).
Products that pip-install ``keel`` without ``oauth2_provider`` can still
import every other ``keel.*`` module without errors.
"""


def _get_base_validator_class():
    """Lazily import the django-oauth-toolkit base validator.

    Importing it eagerly would require ``oauth2_provider`` to be in
    ``INSTALLED_APPS``, which is only true on Keel itself, not on products.
    """
    from oauth2_provider.oauth2_validators import OAuth2Validator
    return OAuth2Validator


def _build_validator_class():
    """Construct ``KeelOIDCValidator`` at first use."""
    OAuth2Validator = _get_base_validator_class()

    class KeelOIDCValidator(OAuth2Validator):
        """Adds DockLabs claims to every ID token Keel issues."""

        # Canonical set of DockLabs-specific claims this validator is
        # contracted to emit. Every entry MUST also appear as a key in
        # ``oidc_claim_scope`` below, or django-oauth-toolkit will
        # silently strip it from every issued ID token. Adding a claim
        # here without wiring the scope mapping is the failure mode
        # ``validate_claim_scope`` exists to catch.
        DOCKLABS_CUSTOM_CLAIMS = frozenset({
            'product_access',
            'is_state_user',
            'agency_abbr',
            'organization',
            'organization_name',
            # AI gating claims — see the ``ai`` scope mapping below.
            'ai_enabled_products',
            'ai_key_present',
        })

        # django-oauth-toolkit filters OIDC claims by this dict inside
        # ``get_oidc_claims``: a claim is only included in the ID token if
        # the scope it maps to is present in ``request.scopes``. Without
        # extending this mapping, our custom ``product_access`` claim gets
        # silently dropped on the server side even when the client
        # requests the ``product_access`` scope — which is exactly how we
        # spent a couple of hours staring at 403s wondering where the
        # claim went. Merge our DockLabs-specific claims into the base
        # mapping so they pass the scope filter.
        oidc_claim_scope = {
            **OAuth2Validator.oidc_claim_scope,
            'product_access': 'product_access',
            'is_state_user': 'product_access',
            'agency_abbr': 'product_access',
            # Organization claims are gated on a separate ``organization``
            # scope so products that don't need them don't pull org-level
            # data into their token. Products that DO consume them must
            # add ``'organization'`` to their openid_connect APP scope.
            'organization': 'organization',
            'organization_name': 'organization',
            # AI claims gated on a separate ``ai`` scope — same trap as
            # ``product_access``: products that want them must add
            # ``'ai'`` to the openid_connect APP scope, otherwise dot
            # claims are silently scrubbed from every token.
            'ai_enabled_products': 'ai',
            'ai_key_present': 'ai',
        }

        @classmethod
        def validate_claim_scope(cls):
            """Fail loudly if any DockLabs custom claim isn't scoped.

            django-oauth-toolkit's ``get_oidc_claims`` only emits a claim
            whose scope (from ``oidc_claim_scope``) is present in the
            client's requested scopes. A claim that's emitted by
            ``get_additional_claims`` but has no ``oidc_claim_scope``
            entry is silently stripped from every token — a bug that
            only surfaces downstream when a product reads a role the
            IdP never sent.

            Call this at app boot (see ``keel.oidc.apps.ready``) so
            drift is caught at startup rather than at token-issue time.
            Raises ``ImproperlyConfigured`` naming every unscoped claim.

            Also runs the inverse check: every claim that
            ``get_additional_claims`` actually emits must be either a
            standard OIDC claim already in the base validator's
            ``oidc_claim_scope`` OR registered in
            ``DOCKLABS_CUSTOM_CLAIMS``. Adding a new custom claim without
            both entries silently scrubs it from every token.
            """
            from django.core.exceptions import ImproperlyConfigured

            # Forward check: declared claims must be scoped.
            missing = sorted(
                claim for claim in cls.DOCKLABS_CUSTOM_CLAIMS
                if claim not in cls.oidc_claim_scope
            )
            if missing:
                raise ImproperlyConfigured(
                    "KeelOIDCValidator claim drift: the following "
                    "DockLabs custom claims are declared in "
                    "DOCKLABS_CUSTOM_CLAIMS but missing from "
                    f"oidc_claim_scope and will be silently stripped "
                    f"from every issued ID token: {missing}. Add each "
                    "claim to oidc_claim_scope with the gating scope."
                )

            # Inverse check: every custom (non-OIDC-standard) claim in
            # ``oidc_claim_scope`` must also appear in
            # ``DOCKLABS_CUSTOM_CLAIMS``. This catches the symmetric
            # mistake — adding a scope mapping but forgetting the
            # registry entry, which means the runtime emit path
            # in ``get_additional_claims`` never knows about the claim.
            base_claims = set(OAuth2Validator.oidc_claim_scope.keys())
            registered = set(cls.DOCKLABS_CUSTOM_CLAIMS)
            scoped_custom = set(cls.oidc_claim_scope.keys()) - base_claims
            unregistered = sorted(scoped_custom - registered)
            if unregistered:
                raise ImproperlyConfigured(
                    "KeelOIDCValidator registry drift: the following "
                    "claims have entries in oidc_claim_scope but are "
                    f"NOT in DOCKLABS_CUSTOM_CLAIMS: {unregistered}. "
                    "Either add each to DOCKLABS_CUSTOM_CLAIMS (and "
                    "ensure get_additional_claims emits them), or "
                    "remove the oidc_claim_scope entry."
                )

        def get_additional_claims(self, request):
            """Build the DockLabs claims dict for the requesting user.

            ``request`` is an oauthlib Request object whose ``user`` attribute
            is the Django ``KeelUser`` being authenticated.
            """
            user = getattr(request, 'user', None)
            if user is None or not getattr(user, 'is_authenticated', False):
                return {}

            # Standard OIDC profile claims. ``zoneinfo``, ``locale``, and
            # ``picture`` are all standard OIDC claim names that pass
            # through the base validator's existing ``oidc_claim_scope``
            # mapping under the ``profile`` scope without further wiring.
            claims = {
                'email': user.email or '',
                'name': user.get_full_name() or user.username,
                'given_name': user.first_name or '',
                'family_name': user.last_name or '',
                'preferred_username': user.username,
                'zoneinfo': getattr(user, 'timezone', '') or '',
                'locale': getattr(user, 'locale', '') or '',
            }

            # Avatar URL (``picture`` claim). Absolutize when the storage
            # returned a relative path (FileSystemStorage emits
            # ``/media/avatars/...``) so products receiving the JWT can
            # fetch the image without knowing where Keel lives. S3 storage
            # already returns absolute URLs, so the prefix branch is a
            # no-op there.
            try:
                from keel.core.avatars import get_avatar_url
                picture = get_avatar_url(user)
            except Exception:
                picture = ''
            if picture and not picture.startswith(('http://', 'https://')):
                from django.conf import settings as django_settings
                issuer = (
                    getattr(django_settings, 'KEEL_OIDC_ISSUER', '') or ''
                ).rstrip('/')
                if issuer:
                    picture = f'{issuer}{picture}'
                else:
                    # No issuer configured (dev w/o KEEL_OIDC_ISSUER) and
                    # the URL is relative — emitting it would mislead the
                    # consumer. Drop the claim rather than send something
                    # they can't resolve.
                    picture = ''
            if picture:
                claims['picture'] = picture

            # DockLabs user attributes
            if hasattr(user, 'is_state_user'):
                claims['is_state_user'] = bool(user.is_state_user)
            if hasattr(user, 'agency') and getattr(user, 'agency_id', None):
                try:
                    claims['agency_abbr'] = user.agency.abbreviation
                except Exception:
                    pass

            # Per-product role mapping — the heart of suite SSO.
            # Read every active ProductAccess record for this user and embed
            # them as a {product_code: role} dict in the token.
            try:
                from keel.accounts.models import ProductAccess
                access_qs = ProductAccess.objects.filter(
                    user=user,
                    is_active=True,
                ).values_list('product', 'role')
                claims['product_access'] = {p: r for p, r in access_qs}
            except Exception:
                # Table doesn't exist yet (initial migration) or any other
                # error: omit the claim rather than failing token issuance.
                claims['product_access'] = {}

            # Organization claims — what customer this user belongs to.
            # Wrapped in the same defensive try/except as product_access
            # so token issuance survives the schema-then-data migration
            # window where the organization column exists but the table
            # may be empty (CSO finding A5).
            try:
                org = getattr(user, 'organization', None)
                if org is not None:
                    claims['organization'] = org.slug
                    claims['organization_name'] = org.name
                else:
                    # Cross-org superusers (dokadmin) emit explicit None
                    # so consumers can distinguish "user has no org" from
                    # "claim was scrubbed by missing scope."
                    claims['organization'] = None
                    claims['organization_name'] = None
            except Exception:
                claims['organization'] = None
                claims['organization_name'] = None

            # AI gating claims (``ai`` scope). ``ai_enabled_products``
            # is the intersection of org-sub.ai_enabled and per-user
            # ProductAccess.ai_enabled — the set of products where this
            # user can see AI surfaces. ``ai_key_present`` is whether
            # the user has set an Anthropic key on Keel; products use
            # it to decide whether to render AI surfaces in active
            # state or in the "needs key" prompt state without having
            # to make a separate Keel API call.
            try:
                from keel.core.ai_access import ai_enabled_products_for_user
                claims['ai_enabled_products'] = ai_enabled_products_for_user(user)
            except Exception:
                claims['ai_enabled_products'] = []
            try:
                claims['ai_key_present'] = bool(user.has_anthropic_key())
            except Exception:
                claims['ai_key_present'] = False

            return claims

    return KeelOIDCValidator


# Use module-level __getattr__ (PEP 562) so that ``KeelOIDCValidator`` is
# only constructed when something explicitly accesses it. This means that
# importing ``keel.oidc.validators`` is always safe — products that don't
# have ``oauth2_provider`` in INSTALLED_APPS can still have this module
# present in the keel package without crashing.
def __getattr__(name):
    if name == 'KeelOIDCValidator':
        cls = _build_validator_class()
        globals()['KeelOIDCValidator'] = cls
        return cls
    raise AttributeError(f"module 'keel.oidc.validators' has no attribute {name!r}")
