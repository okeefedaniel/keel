"""Configurable Microsoft Entra ID SSO adapters for DockLabs products.

Usage in product settings.py:

    ACCOUNT_ADAPTER = 'core.sso.MyProductAccountAdapter'
    SOCIALACCOUNT_ADAPTER = 'core.sso.MyProductSocialAccountAdapter'

In product core/sso.py:

    from keel.core.sso import KeelAccountAdapter, KeelSocialAccountAdapter

    ROLE_DOMAIN_MAP = {
        'ct.gov': 'relationship_manager',
        'state.ct.us': 'relationship_manager',
    }

    class MyProductAccountAdapter(KeelAccountAdapter):
        pass

    class MyProductSocialAccountAdapter(KeelSocialAccountAdapter):
        role_domain_map = ROLE_DOMAIN_MAP
        default_role = 'analyst'
"""
import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


class KeelAccountAdapter(DefaultAccountAdapter):
    """Base account adapter with standard redirects.

    Suppresses outbound confirmation emails when the user authenticated
    via the Keel OIDC IdP — Keel has already verified the address (and
    products may not have an email backend configured at all). This
    keeps the OIDC callback from 500-ing during signup just because we
    can't reach a mail server.
    """

    login_redirect_url = '/dashboard/'
    signup_redirect_url = '/dashboard/'

    def get_login_redirect_url(self, request):
        # Prefer the product's LOGIN_REDIRECT_URL setting (e.g. Helm uses
        # '/helm/', Harbor uses '/harbor/dashboard/'). Fall back to the
        # class default for products that don't set it.
        return getattr(settings, 'LOGIN_REDIRECT_URL', None) or self.login_redirect_url

    def get_signup_redirect_url(self, request):
        return getattr(settings, 'LOGIN_REDIRECT_URL', None) or self.signup_redirect_url

    def send_confirmation_mail(self, request, emailconfirmation, signup):
        # Skip the confirmation mail for users coming from Keel OIDC.
        # We detect this by looking for the claims we stash in session.
        try:
            if request.session.get('keel_oidc_claims'):
                return
        except Exception:
            pass
        return super().send_confirmation_mail(request, emailconfirmation, signup)

    def send_mail(self, template_prefix, email, context):
        # Defensive: if EMAIL_BACKEND import or send fails for any reason
        # (e.g., misconfigured Resend in dev), don't blow up the request.
        # Real product code should still wire EMAIL_BACKEND properly.
        try:
            return super().send_mail(template_prefix, email, context)
        except Exception:
            logger.exception('Failed to send mail %s to %s', template_prefix, email)
            return None


#: Provider slug used for the Keel OIDC provider (matches provider_id in
#: SOCIALACCOUNT_PROVIDERS['openid_connect'] config on each product).
KEEL_OIDC_PROVIDER_ID = 'keel'


def _is_keel_provider(sociallogin) -> bool:
    """True when this social login is coming from the Keel OIDC IdP.

    Allauth's openid_connect provider reports `provider` as the configured
    `provider_id` (e.g. 'keel'), so we just need to match on that string.
    """
    try:
        return sociallogin.account.provider == KEEL_OIDC_PROVIDER_ID
    except Exception:
        return False


def _extract_keel_claims(sociallogin) -> dict:
    """Pull OIDC claims out of the sociallogin extra_data.

    allauth's openid_connect provider stores the ID token claims and the
    userinfo response under nested keys::

        extra_data = {
            "userinfo": {"email": ..., "product_access": ..., ...},
            "id_token": {"email": ..., "product_access": ..., ...},
        }

    We prefer userinfo (it usually has the most fields), fall back to
    id_token, and as a final fallback return the top-level dict for
    backwards compatibility with older allauth versions that flattened.
    """
    try:
        data = sociallogin.account.extra_data or {}
        if not isinstance(data, dict):
            return {}
        # New layout (allauth 65+)
        userinfo = data.get('userinfo')
        if isinstance(userinfo, dict) and userinfo:
            # Merge id_token claims on top so product_access from the
            # signed token wins over anything userinfo might omit.
            merged = dict(userinfo)
            id_token = data.get('id_token')
            if isinstance(id_token, dict):
                for k, v in id_token.items():
                    if v is not None and k not in merged:
                        merged[k] = v
            return merged
        id_token = data.get('id_token')
        if isinstance(id_token, dict) and id_token:
            return id_token
        # Legacy flat layout
        return data
    except Exception:
        pass
    return {}


class KeelSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Base social account adapter for DockLabs SSO.

    Handles two provider families:

    1. **Microsoft Entra ID** (direct, standalone mode) — subclass and set
       ``role_domain_map`` / ``default_role`` / ``state_user_domains`` to
       drive role inference from email domain.

    2. **Keel OIDC** (suite mode, Phase 2b) — ID token from Keel already
       contains a ``product_access`` claim plus profile fields. We skip
       domain heuristics and drive role assignment directly from the
       claim. The claim dict is also stashed in ``request.session`` under
       ``keel_oidc_claims`` so :class:`ProductAccessMiddleware` can read
       it on subsequent requests without a DB hit.

    Subclass and set:
    - role_domain_map: dict mapping email domains to role strings
    - default_role: fallback role for unknown domains
    - state_user_domains: set of domains that mark a user as is_state_user=True
    """

    role_domain_map: dict = {}
    default_role: str = 'analyst'
    state_user_domains: set = set()

    # ------------------------------------------------------------------
    # Pre-login linking
    # ------------------------------------------------------------------
    def pre_social_login(self, request, sociallogin):
        """Link social account to existing user by email and stash claims.

        For Keel OIDC logins we also immediately store the ``product_access``
        and related claims in the request session so that
        :class:`ProductAccessMiddleware` can read them on *this* request,
        not just the next one.
        """
        if _is_keel_provider(sociallogin):
            claims = _extract_keel_claims(sociallogin)
            if hasattr(request, 'session'):
                request.session['keel_oidc_claims'] = {
                    'product_access': claims.get('product_access') or {},
                    'is_state_user': bool(claims.get('is_state_user')),
                    'agency_abbr': claims.get('agency_abbr') or '',
                    'sub': claims.get('sub') or '',
                }
            email = claims.get('email', '')
            if email and not sociallogin.is_existing:
                User = get_user_model()
                try:
                    user = User.objects.get(email__iexact=email)
                    sociallogin.connect(request, user)
                    logger.info(
                        'SSO: Linked Keel OIDC account to existing user %s',
                        user.username,
                    )
                except User.DoesNotExist:
                    pass
            # Keep ProductAccess in sync with the latest claim on every login
            # (save_user only fires on first sign-in, so returning users would
            # otherwise keep stale access rows if Keel admin changed their role).
            if sociallogin.is_existing and sociallogin.user and sociallogin.user.pk:
                product_access = claims.get('product_access') or {}
                if isinstance(product_access, dict) and product_access:
                    try:
                        from keel.accounts.models import ProductAccess
                        for prod, role in product_access.items():
                            if not prod or not role:
                                continue
                            ProductAccess.objects.update_or_create(
                                user=sociallogin.user,
                                product=str(prod).lower(),
                                defaults={'role': role, 'is_active': True},
                            )
                    except Exception:
                        logger.exception(
                            'SSO: Failed to refresh product_access for %s',
                            sociallogin.user,
                        )
            return

        # --- Microsoft Entra ID path (unchanged) --------------------------
        if sociallogin.is_existing:
            return
        email = (sociallogin.account.extra_data.get('mail')
                 or sociallogin.account.extra_data.get('userPrincipalName', ''))
        if not email:
            return
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email)
            sociallogin.connect(request, user)
            logger.info('SSO: Linked Microsoft account to existing user %s', user.username)
        except User.DoesNotExist:
            pass

    def populate_user(self, request, sociallogin, data):
        """Fill user fields from Microsoft profile data or Keel OIDC claims."""
        user = super().populate_user(request, sociallogin, data)
        User = get_user_model()

        # --- Keel OIDC path ---------------------------------------------
        if _is_keel_provider(sociallogin):
            claims = _extract_keel_claims(sociallogin)
            email = claims.get('email') or data.get('email') or ''
            user.email = email
            user.first_name = claims.get('given_name') or data.get('first_name') or ''
            user.last_name = claims.get('family_name') or data.get('last_name') or ''
            # Use preferred_username from claim if present; else derive from email
            preferred = claims.get('preferred_username') or ''
            if not user.username:
                base = (preferred or (email.split('@')[0] if email else '')).lower().replace('.', '_')
                username = base
                counter = 1
                while username and User.objects.filter(username=username).exists():
                    username = f'{base}_{counter}'
                    counter += 1
                user.username = username or base
            if hasattr(user, 'is_state_user'):
                user.is_state_user = bool(claims.get('is_state_user'))
            # Resolve role for the current product from the product_access claim
            product = getattr(settings, 'KEEL_PRODUCT_NAME', '').lower()
            product_access = claims.get('product_access') or {}
            if isinstance(product_access, dict) and product:
                user._sso_role = product_access.get(product) or self.default_role
            else:
                user._sso_role = self.default_role
            user.accepted_terms = True
            # Link agency by claim-provided abbreviation
            agency_abbr = claims.get('agency_abbr') or ''
            if agency_abbr:
                try:
                    from keel.accounts.models import Agency
                    agency = Agency.objects.filter(
                        abbreviation__iexact=agency_abbr, is_active=True,
                    ).first()
                    if agency:
                        user.agency = agency
                except Exception:
                    pass
            return user

        # --- Microsoft Entra ID path (unchanged) -------------------------
        extra = sociallogin.account.extra_data
        email = data.get('email') or extra.get('mail') or extra.get('userPrincipalName', '')

        user.email = email
        user.first_name = data.get('first_name') or extra.get('givenName', '')
        user.last_name = data.get('last_name') or extra.get('surname', '')

        # Generate unique username from email
        if not user.username and email:
            base = email.split('@')[0].lower().replace('.', '_')
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f'{base}_{counter}'
                counter += 1
            user.username = username

        # Determine role from email domain
        domain = email.split('@')[-1].lower() if '@' in email else ''
        role = self.role_domain_map.get(domain, self.default_role)
        user.is_state_user = bool(self.role_domain_map.get(domain)) or domain in self.state_user_domains

        # Store role temporarily for save_user to create ProductAccess
        user._sso_role = role

        user.accepted_terms = True

        # Link to agency by domain prefix
        if user.is_state_user:
            try:
                from keel.accounts.models import Agency
                domain_prefix = domain.split('.')[0].upper()
                agency = Agency.objects.filter(
                    abbreviation__iexact=domain_prefix, is_active=True,
                ).first()
                if agency:
                    user.agency = agency
            except Exception:
                pass

        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        if user.accepted_terms and not user.accepted_terms_at:
            from django.utils import timezone
            user.accepted_terms_at = timezone.now()
            user.save(update_fields=['accepted_terms_at'])

        current_product = getattr(settings, 'KEEL_PRODUCT_NAME', '').lower()

        # --- Keel OIDC path: mirror the full product_access claim --------
        if _is_keel_provider(sociallogin):
            claims = _extract_keel_claims(sociallogin)
            product_access = claims.get('product_access') or {}
            if isinstance(product_access, dict) and product_access:
                try:
                    from keel.accounts.models import ProductAccess
                    for prod, role in product_access.items():
                        if not prod or not role:
                            continue
                        ProductAccess.objects.update_or_create(
                            user=user,
                            product=str(prod).lower(),
                            defaults={'role': role, 'is_active': True},
                        )
                    logger.info(
                        'SSO: Mirrored Keel product_access claim for %s: %s',
                        user, list(product_access.keys()),
                    )
                except Exception:
                    logger.exception(
                        'SSO: Failed to mirror product_access claim for %s', user,
                    )
            return user

        # --- Microsoft / default path: grant access to current product ---
        role = getattr(user, '_sso_role', self.default_role)
        if current_product:
            try:
                from keel.accounts.models import ProductAccess
                ProductAccess.objects.get_or_create(
                    user=user,
                    product=current_product,
                    defaults={'role': role, 'is_active': True},
                )
                logger.info('SSO: Granted %s access to %s as %s', user, current_product, role)
            except Exception:
                logger.exception('SSO: Failed to create ProductAccess for %s', user)

        return user
