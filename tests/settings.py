"""Django settings for keel's own pytest run.

Keel-the-IdP authenticates with Django's native auth and deliberately does
not install allauth (see ``keel_site.settings``). But parts of keel that
ship to products — ``keel.feed.resolve_user_from_sub`` resolving an OIDC
``sub`` through ``allauth.socialaccount.models.SocialAccount`` — only ever
run in a consumer that installed the ``[sso]`` extra. Their tests need the
allauth models to be loadable, which means allauth has to be in
INSTALLED_APPS for the test process.

So the test run uses the production IdP settings plus the allauth apps a
consuming product would have. Everything else is inherited unchanged.
"""
from keel_site.settings import *  # noqa: F401,F403
from keel_site.settings import INSTALLED_APPS, MIDDLEWARE

try:
    import allauth  # noqa: F401
except ImportError:
    # keel's [sso] extra isn't installed — tests that need SocialAccount
    # skip themselves via apps.is_installed().
    HAS_ALLAUTH = False
else:
    HAS_ALLAUTH = True
    INSTALLED_APPS = INSTALLED_APPS + [
        'allauth',
        'allauth.account',
        'allauth.socialaccount',
    ]
    MIDDLEWARE = MIDDLEWARE + ['allauth.account.middleware.AccountMiddleware']
