"""Keel OIDC identity provider — makes Keel an OAuth2/OIDC server.

Each DockLabs product authenticates by redirecting to Keel and receiving
an ID token containing a `product_access` claim. Standalone deployments
fall back to local Django auth when this app is not installed.
"""
from django.apps import AppConfig


class KeelOIDCConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'keel.oidc'
    label = 'keel_oidc'
    verbose_name = 'Keel OIDC Identity Provider'

    def ready(self):
        # Fail startup if a DockLabs custom claim was added to the
        # validator without a matching `oidc_claim_scope` entry — the
        # drift would otherwise silently strip the claim from every
        # token. See `KeelOIDCValidator.validate_claim_scope`.
        try:
            from keel.oidc.validators import KeelOIDCValidator
        except ImportError:
            # oauth2_provider isn't installed; this app shouldn't be
            # enabled, but don't crash on introspection commands.
            return
        KeelOIDCValidator.validate_claim_scope()
