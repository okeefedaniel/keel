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
