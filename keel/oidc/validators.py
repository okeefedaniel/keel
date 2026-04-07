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

        def get_additional_claims(self, request):
            """Build the DockLabs claims dict for the requesting user.

            ``request`` is an oauthlib Request object whose ``user`` attribute
            is the Django ``KeelUser`` being authenticated.
            """
            user = getattr(request, 'user', None)
            if user is None or not getattr(user, 'is_authenticated', False):
                return {}

            # Standard OIDC profile claims
            claims = {
                'email': user.email or '',
                'name': user.get_full_name() or user.username,
                'given_name': user.first_name or '',
                'family_name': user.last_name or '',
                'preferred_username': user.username,
            }

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
