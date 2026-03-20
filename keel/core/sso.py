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
    """Base account adapter with standard redirects."""

    login_redirect_url = '/dashboard/'
    signup_redirect_url = '/dashboard/'

    def get_login_redirect_url(self, request):
        return self.login_redirect_url

    def get_signup_redirect_url(self, request):
        return self.signup_redirect_url


class KeelSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Base social account adapter for Microsoft Entra ID SSO.

    Subclass and set:
    - role_domain_map: dict mapping email domains to role strings
    - default_role: fallback role for unknown domains
    - state_user_domains: set of domains that mark a user as is_state_user=True
    """

    role_domain_map: dict = {}
    default_role: str = 'analyst'
    state_user_domains: set = set()

    def pre_social_login(self, request, sociallogin):
        """Link Microsoft account to existing user by email."""
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
        """Fill user fields from Microsoft profile data."""
        user = super().populate_user(request, sociallogin, data)
        User = get_user_model()
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

        # Create ProductAccess for the current product
        product = getattr(settings, 'KEEL_PRODUCT_NAME', '').lower()
        role = getattr(user, '_sso_role', self.default_role)
        if product:
            try:
                from keel.accounts.models import ProductAccess
                ProductAccess.objects.get_or_create(
                    user=user,
                    product=product,
                    defaults={'role': role, 'is_active': True},
                )
                logger.info('SSO: Granted %s access to %s as %s', user, product, role)
            except Exception:
                logger.exception('SSO: Failed to create ProductAccess for %s', user)

        return user
