"""Django settings for keel.docklabs.ai — the Keel admin console.

Reads configuration from environment variables (Railway sets these automatically).
"""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 'yes')
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', 'https://keel.docklabs.ai').split(',')
]

# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    # Third party
    'oauth2_provider',  # Phase 2b: Keel as OIDC IdP
    # Keel modules
    'keel.accounts',
    'keel.requests',
    'keel.notifications',
    'keel.core',
    'keel.security',
    'keel.periods',
    'keel.reporting',
    'keel.compliance',
    'keel.calendar',
    'keel.oidc.apps.KeelOIDCConfig',  # Phase 2b: OIDC validator + claims
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'keel.security.middleware.SecurityHeadersMiddleware',
    'keel.security.middleware.FailedLoginMonitor',
    'keel_site.middleware.APICorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'keel.accounts.middleware.ProductAccessMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'keel.core.middleware.AuditMiddleware',
]

ROOT_URLCONF = 'keel_site.urls'

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'keel_site' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'keel.core.context_processors.site_context',
                'keel.core.context_processors.fleet_context',
                'keel.core.context_processors.breadcrumb_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'keel_site.wsgi.application'

# ---------------------------------------------------------------------------
# Database — Railway provides DATABASE_URL automatically
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{BASE_DIR / "db.sqlite3"}')

DATABASES = {
    'default': dj_database_url.parse(DATABASE_URL),
    # Keel admin console is the primary user of the shared DB,
    # so keel DB = default DB here. The router is still listed so
    # that products installing keel as a library can override with
    # a separate keel database.
    'keel': dj_database_url.parse(DATABASE_URL),
}

# When default and keel point to the same database (single-DB deployment),
# skip the router so Django can migrate all tables to one DB without conflict.
# Products with a separate keel DB will add the router in their own settings.
DATABASE_ROUTERS = []

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = 'keel_accounts.KeelUser'
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# Email — console in dev, SMTP in production
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.migadu.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1')
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() in ('true', '1')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@docklabs.ai')
EMAIL_TIMEOUT = 10  # seconds — prevent SMTP hangs from blocking notification threads
PASSWORD_RESET_TIMEOUT = 259200  # 3 days in seconds

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Minimum password length (match all DockLabs products)
AUTH_PASSWORD_VALIDATORS[1]['OPTIONS'] = {'min_length': 10}

# ---------------------------------------------------------------------------
# OIDC Identity Provider (Phase 2b)
# ---------------------------------------------------------------------------
# Keel acts as the OAuth2/OIDC provider for the entire DockLabs suite.
# Each product is a confidential client that authenticates by redirecting
# users here. The signing key is required in production; in dev a temporary
# key is generated on first run if KEEL_OIDC_PRIVATE_KEY is not set.
#
# To generate a signing key (one-time, run locally):
#   openssl genrsa -out keel_oidc_key.pem 2048
#   cat keel_oidc_key.pem  # paste into Railway env var KEEL_OIDC_PRIVATE_KEY

KEEL_OIDC_PRIVATE_KEY = os.environ.get('KEEL_OIDC_PRIVATE_KEY', '')

if not KEEL_OIDC_PRIVATE_KEY and DEBUG:
    # Auto-generate an ephemeral key for local development. NEVER do this
    # in production — every restart would invalidate previously issued tokens.
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        _key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEEL_OIDC_PRIVATE_KEY = _key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
    except ImportError:
        pass  # cryptography not installed; OIDC will be unavailable in dev

OAUTH2_PROVIDER = {
    'OIDC_ENABLED': True,
    'OIDC_RSA_PRIVATE_KEY': KEEL_OIDC_PRIVATE_KEY,
    'OIDC_ISS_ENDPOINT': os.environ.get('KEEL_OIDC_ISSUER', 'https://keel.docklabs.ai'),
    'PKCE_REQUIRED': True,
    'OAUTH2_VALIDATOR_CLASS': 'keel.oidc.validators.KeelOIDCValidator',
    'SCOPES': {
        'openid': 'OpenID Connect',
        'profile': 'User profile',
        'email': 'Email address',
        'product_access': 'DockLabs per-product role assignments',
    },
    'DEFAULT_SCOPES': ['openid', 'profile', 'email', 'product_access'],
    # 1 hour access tokens, 14 day refresh tokens
    'ACCESS_TOKEN_EXPIRE_SECONDS': 3600,
    'REFRESH_TOKEN_EXPIRE_SECONDS': 14 * 24 * 3600,
    'ROTATE_REFRESH_TOKEN': True,
    # RP-initiated logout (OIDC end_session_endpoint) so that clicking
    # "log out" on any product also kills the Keel IdP session. Without
    # this, a user who logs out of harbor and then clicks "Sign in with
    # DockLabs" is silently re-authed from the still-active Keel cookie.
    'OIDC_RP_INITIATED_LOGOUT_ENABLED': True,
    # Skip the "are you sure?" confirmation page — the click-through
    # friction defeats the purpose of chaining logouts across the suite.
    'OIDC_RP_INITIATED_LOGOUT_ALWAYS_PROMPT': False,
    # STRICT validation: django-oauth-toolkit checks the requested
    # post_logout_redirect_uri against each Application's registered
    # ``post_logout_redirect_uris`` list. An unregistered URI is rejected
    # before the logout completes. This closes the open-redirect path
    # that would otherwise let an attacker bounce an authenticated user
    # to an arbitrary external URL after logout.
    'OIDC_RP_INITIATED_LOGOUT_STRICT_REDIRECT_URIS': True,
}

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files — WhiteNoise serves them in production
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# ---------------------------------------------------------------------------
# Keel configuration
# ---------------------------------------------------------------------------
KEEL_PRODUCT_NAME = 'Keel'
KEEL_PRODUCT_CODE = 'keel'
KEEL_PRODUCT_ICON = 'bi-gear-wide-connected'
KEEL_PRODUCT_SUBTITLE = 'DockLabs Admin Console'
KEEL_FLEET_PRODUCTS = [
    {'name': 'Helm', 'label': 'Helm', 'code': 'helm', 'url': '/'},
    {'name': 'Beacon', 'label': 'Beacon', 'code': 'beacon', 'url': '/'},
    {'name': 'Harbor', 'label': 'Harbor', 'code': 'harbor', 'url': '/'},
    {'name': 'Bounty', 'label': 'Bounty', 'code': 'bounty', 'url': '/'},
    {'name': 'Lookout', 'label': 'Lookout', 'code': 'lookout', 'url': '/'},
]
KEEL_GATE_ACCESS = False  # Keel admin console doesn't gate itself

# Notification system — point to concrete models in keel_accounts
KEEL_NOTIFICATION_MODEL = 'keel_accounts.Notification'
KEEL_NOTIFICATION_PREFERENCE_MODEL = 'keel_accounts.NotificationPreference'
KEEL_NOTIFICATION_LOG_MODEL = 'keel_accounts.NotificationLog'
KEEL_API_KEY = os.environ.get('KEEL_API_KEY', '')  # Shared key for product → Keel API (legacy)

# Per-product API keys — preferred over ``KEEL_API_KEY``. Each product is
# provisioned its own key so a compromised product container can only
# forge requests attributed to itself, not to the whole fleet. Format:
# ``KEEL_API_KEY_<PRODUCT>`` env vars map into this dict. Unset entries
# simply do not create an accepted credential for that product.
KEEL_PRODUCT_API_KEYS = {
    code: os.environ.get(f'KEEL_API_KEY_{code.upper()}', '')
    for code in (
        'helm', 'harbor', 'beacon', 'lookout', 'bounty',
        'admiralty', 'purser', 'manifest', 'yeoman',
    )
}
KEEL_PRODUCT_API_KEYS = {k: v for k, v in KEEL_PRODUCT_API_KEYS.items() if v}
DEMO_MODE = os.environ.get('DEMO_MODE', 'False').lower() in ('true', '1', 'yes')
DEMO_ROLES = ['admin', 'system_admin']
KEEL_AUDIT_LOG_MODEL = 'keel_accounts.AuditLog'

# SMS via Twilio (set env vars on Railway to enable)
KEEL_SMS_BACKEND = os.environ.get('KEEL_SMS_BACKEND', None)  # Set to 'twilio' to enable
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')

# Calendar sync (keel.calendar)
KEEL_CALENDAR_PROVIDER = os.environ.get('KEEL_CALENDAR_PROVIDER', None)  # 'google' or 'microsoft'
KEEL_CALENDAR_EVENT_MODEL = None  # Products set this to their concrete model
KEEL_CALENDAR_SYNC_LOG_MODEL = None

# ---------------------------------------------------------------------------
# Security
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
# ---------------------------------------------------------------------------
if not DEBUG:
    # Railway's proxy handles HTTP→HTTPS redirect; don't do it in Django
    # (breaks Railway's internal healthcheck which sends plain HTTP)
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days (pre-gov-launch; tighten before go-live)
SESSION_SAVE_EVERY_REQUEST = True

# Upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# ---------------------------------------------------------------------------
# Sites framework
# ---------------------------------------------------------------------------
SITE_ID = 1
SITE_DOMAIN = os.environ.get('SITE_DOMAIN', 'keel.docklabs.ai')

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {'level': 'WARNING'},
        'keel': {'level': 'DEBUG' if DEBUG else 'INFO'},
    },
}
