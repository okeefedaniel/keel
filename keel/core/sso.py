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

from keel.core.utils import get_product_code

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

    def is_open_for_signup(self, request):
        """Close public signup across the suite by default.

        Three modes:
        - Suite (KEEL_OIDC_CLIENT_ID set, not DEMO_MODE): signup is
          FORCED CLOSED — users must come through Keel OIDC. The
          KEEL_ALLOW_SIGNUP setting is ignored in this mode to prevent
          accidental local-only user creation that can't SSO.
        - Demo (DEMO_MODE true): gated by KEEL_ALLOW_SIGNUP. Demo
          instances often want signup open so evaluators can try the
          product without coordination.
        - Standalone (KEEL_OIDC_CLIENT_ID unset): gated by
          KEEL_ALLOW_SIGNUP. Products that want self-service signup
          can opt in (e.g. a future grantee self-registration flow
          on Harbor in a solo deployment).
        """
        from keel.core.utils import is_suite_mode
        if is_suite_mode():
            return False
        return bool(getattr(settings, 'KEEL_ALLOW_SIGNUP', False))

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

    #: Allauth mail templates we NEVER send, suite-wide, regardless of
    #: allauth's own settings. ``account/email/unknown_account`` is the
    #: mail allauth sends to an address that has NO account when someone
    #: POSTs it to the password-reset form (allauth's default
    #: ``ACCOUNT_PREVENT_ENUMERATION = True`` behavior). Because the
    #: reset endpoint is public and unauthenticated, that turns every
    #: product into an open relay: an attacker scripts a scraped list of
    #: third-party addresses through ``/accounts/password/reset/`` and we
    #: dutifully email each stranger from ``info@docklabs.ai`` — cold mail
    #: that torches the sending domain's reputation and lands real
    #: invitations in spam. (Observed 2026-07: 97 of 100 outbound emails
    #: were ``[Harbor]/[Bounty] Unknown Account`` to scraped business
    #: addresses.) Suppressing the send here keeps allauth's anti-
    #: enumeration *response* intact — the reset page still shows the same
    #: neutral "check your email" message — while never actually mailing
    #: a non-account. Every product routes through this adapter, so the
    #: fix lands suite-wide via the keel pin and can't be forgotten by a
    #: new product. See also ``ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS = False`` in
    #: each product's settings (belt-and-suspenders / deployable without a
    #: keel bump).
    SUPPRESSED_MAIL_TEMPLATES = frozenset({
        'account/email/unknown_account',
    })

    def send_mail(self, template_prefix, email, context):
        # Hard-drop the unknown-account (password-reset-for-nonexistent)
        # email so the reset endpoint can't be abused as a spam relay.
        # Opt back in per product with KEEL_EMAIL_UNKNOWN_ACCOUNTS=True
        # only if you have a genuine self-service standalone deployment
        # that needs it (no suite product does).
        if (
            template_prefix in self.SUPPRESSED_MAIL_TEMPLATES
            and not getattr(settings, 'KEEL_EMAIL_UNKNOWN_ACCOUNTS', False)
        ):
            logger.warning(
                'Suppressed abusive allauth mail %s to %s (password-reset '
                'relay guard)', template_prefix, email,
                extra={'security_event': 'unknown_account_mail_suppressed'},
            )
            return None
        # Defensive: if EMAIL_BACKEND import or send fails for any reason
        # (e.g., misconfigured Resend in dev), don't blow up the request.
        # Real product code should still wire EMAIL_BACKEND properly.
        try:
            return super().send_mail(template_prefix, email, context)
        except Exception:
            logger.exception('Failed to send mail %s to %s', template_prefix, email)
            return None

    #: Allauth message templates we suppress suite-wide. SSO is meant to
    #: be "sign once and stay on", so telling the user "Successfully
    #: signed in as <X>" on every product they visit is noise — worse,
    #: stale login messages accumulate in the session and render in
    #: batches the next time a template iterates ``messages``, which is
    #: how users end up seeing two "signed in as" toasts at once.
    #:
    #: ``email_confirmation_sent.txt`` is also silenced: OIDC logins
    #: are authoritative (Keel has already verified the address), so
    #: the confirmation email is never actually sent and the toast
    #: would be a lie. Signup via the local form is rare enough that
    #: product staff can tell users to check their inbox out-of-band.
    SUPPRESSED_MESSAGE_TEMPLATES = frozenset({
        'account/messages/logged_in.txt',
        'account/messages/logged_out.txt',
        'account/messages/email_confirmation_sent.txt',
    })

    #: Substrings of rendered message text that we also suppress, as a
    #: belt-and-suspenders over :attr:`SUPPRESSED_MESSAGE_TEMPLATES`.
    #: Some allauth code paths (especially socialaccount) bypass
    #: ``add_message`` and call ``django.contrib.messages.add_message``
    #: directly with a pre-rendered string — matching by substring
    #: catches those too. Case-insensitive.
    SUPPRESSED_MESSAGE_SUBSTRINGS = (
        'signed in as',
        'signed out',
        'email b-e-e-n sent',  # placeholder, kept short-circuited
    )

    def add_message(
        self,
        request,
        level,
        message_template=None,
        message_context=None,
        extra_tags='',
        message=None,
    ):
        if message_template in self.SUPPRESSED_MESSAGE_TEMPLATES:
            return
        if isinstance(message, str):
            lower = message.lower()
            if any(s in lower for s in self.SUPPRESSED_MESSAGE_SUBSTRINGS):
                return
        return super().add_message(
            request,
            level,
            message_template=message_template,
            message_context=message_context,
            extra_tags=extra_tags,
            message=message,
        )


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


def _mirror_product_access(user, claims) -> int:
    """Mirror per-product fields from a Keel JWT into local ``ProductAccess``.

    Single call site for both ``pre_social_login`` (returning users) and
    ``save_user`` (new users). Drives field assignments off
    ``keel.accounts.models.SYNCED_FIELDS`` so adding a new field to
    ``ProductAccess`` only requires updating the registry — not these
    two adapter call sites.

    Returns the number of rows written (zero on any failure or empty
    claim set). The caller is expected to have already vetted that
    this login came from the Keel OIDC provider.
    """
    try:
        from keel.accounts.models import ProductAccess, mirror_synced_fields
    except Exception:
        logger.exception(
            'SSO: keel.accounts not importable; cannot mirror product_access'
        )
        return 0
    defaults_by_code = mirror_synced_fields(claims)
    if not defaults_by_code:
        return 0
    written = 0
    try:
        for code, defaults in defaults_by_code.items():
            # Drop any defaults the local schema doesn't have. Older
            # product DBs migrated before a new ProductAccess column
            # exists would otherwise crash the entire login.
            safe_defaults = {
                k: v for k, v in defaults.items()
                if _product_access_has_field(ProductAccess, k)
            }
            if not safe_defaults:
                continue
            ProductAccess.objects.update_or_create(
                user=user, product=code, defaults=safe_defaults,
            )
            written += 1
    except Exception:
        logger.exception(
            'SSO: Failed to mirror product_access for %s', user,
        )
        return written
    if written:
        logger.info(
            'SSO: Mirrored Keel ProductAccess claims for %s: %d row(s)',
            user, written,
        )
    return written


def _product_access_has_field(model, field_name) -> bool:
    """Return True when the local ProductAccess model declares this field.

    Cached on the function object — products don't add fields at runtime.
    """
    cache = _product_access_has_field._cache
    key = (model, field_name)
    if key in cache:
        return cache[key]
    try:
        model._meta.get_field(field_name)
        cache[key] = True
    except Exception:
        cache[key] = False
    return cache[key]


_product_access_has_field._cache = {}


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


def _maybe_hydrate_local_ai_key(sociallogin) -> None:
    """One-shot: pull the user's Anthropic key from Keel at login into the
    product-LOCAL encrypted field. Nothing is persisted beyond that field —
    no OIDC token is stored (Phase B of the invisible-Keel AI-key design).

    This is what delivers "enter once, see everywhere" without token-at-rest:
    allauth holds a login-fresh access token in memory (``sociallogin.token``)
    even with ``SOCIALACCOUNT_STORE_TOKENS=False``, so we spend it once here to
    read ``GET /api/v1/ai/key/`` and copy the key locally, then discard it.

    Runs only when ALL of:
      - this product stores the key locally (``KEEL_LOCAL_AI_KEY``),
      - the local field is empty (never clobber an in-product edit or a key
        hydrated on a prior login),
      - allauth handed us a login-fresh access token in memory.

    Best-effort: any failure is swallowed so login is never blocked. A user
    with no key on Keel simply gets a 404 → local field stays empty → the
    in-product needs-key prompt shows, exactly as intended.
    """
    try:
        from keel.core.utils import local_ai_key_enabled
        if not local_ai_key_enabled():
            return
        if not _is_keel_provider(sociallogin):
            return
        user = getattr(sociallogin, 'user', None)
        if user is None or not getattr(user, 'pk', None):
            return
        # The encrypted local field must exist on this user model.
        if not hasattr(user, 'anthropic_api_key'):
            return
        # Never overwrite a locally-stored key (in-product edit or a prior
        # hydration). The local field is the source of truth once set.
        has_local = getattr(user, 'has_anthropic_key', None)
        if callable(has_local) and has_local():
            return
        token_obj = getattr(sociallogin, 'token', None)
        access_token = getattr(token_obj, 'token', '') if token_obj else ''
        if not access_token:
            return
        from keel.core.ai import fetch_ai_key_with_token
        key = fetch_ai_key_with_token(access_token)
        if key:
            user.anthropic_api_key = key
            user.save(update_fields=['anthropic_api_key_encrypted'])
            logger.info('SSO: hydrated local Anthropic key for user=%s', user.pk)
    except Exception:
        logger.exception('SSO: local AI-key hydration failed (non-fatal)')


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

    def is_open_for_signup(self, request, sociallogin):
        """Allow OIDC auto-provisioning even when public signup is closed.

        ``KeelAccountAdapter.is_open_for_signup`` force-closes signup in
        suite mode so the local form can't create users that bypass Keel.
        But Keel-issued OIDC logins are already vetted by the IdP — when
        ``pre_social_login`` can't find a matching local user, allauth
        should be allowed to provision one rather than dead-end on
        ``signup_closed.html``. Without this override, every new user
        added in Keel admin requires a manual ``createsuperuser``-style
        seed in every product's DB before they can SSO.

        Form-based signups still fall through to the account adapter's
        ``is_open_for_signup``, which stays closed in suite mode.
        """
        if _is_keel_provider(sociallogin):
            return True
        return super().is_open_for_signup(request, sociallogin)

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
                from django.utils import timezone
                request.session['keel_oidc_claims'] = {
                    'product_access': claims.get('product_access') or {},
                    'is_state_user': bool(claims.get('is_state_user')),
                    'agency_abbr': claims.get('agency_abbr') or '',
                    'sub': claims.get('sub') or '',
                    # Organization claims — present only when the
                    # product's openid_connect APP scope includes
                    # 'organization'. Defaults to None when the scope
                    # isn't requested OR when the user is a cross-org
                    # superuser. Products consume via
                    # ProductAccessMiddleware → request.organization_slug.
                    'organization': claims.get('organization') or None,
                    'organization_name': claims.get('organization_name') or None,
                }
                # Marker used by SessionFreshnessMiddleware to detect
                # that the user has logged out at Keel since this
                # session was established. Compared against the
                # last_logout_at value returned by /oauth/session-status/.
                request.session['keel_oidc_login_at'] = timezone.now().isoformat()
            email = claims.get('email', '')
            preferred = (claims.get('preferred_username') or '').strip()
            if not sociallogin.is_existing:
                User = get_user_model()
                linked = None
                # 1. Prefer an exact username match against the JWT's
                #    preferred_username — Keel's canonical identity —
                #    because email can legitimately change over time
                #    (e.g. the dokadmin → dok@docklabs.ai email migration).
                if preferred:
                    try:
                        linked = User.objects.get(username__iexact=preferred)
                    except User.DoesNotExist:
                        pass
                # 2. Fall back to email match for products whose local
                #    user was created with a different username but the
                #    same email.
                if linked is None and email:
                    try:
                        linked = User.objects.get(email__iexact=email)
                    except (User.DoesNotExist, User.MultipleObjectsReturned):
                        pass
                if linked is not None:
                    sociallogin.connect(request, linked)
                    logger.info(
                        'SSO: Linked Keel OIDC account to existing user %s',
                        linked.username,
                    )
            # Keep identity + ProductAccess in sync with the latest claims on
            # every login. save_user only fires on first sign-in, so returning
            # users would otherwise drift whenever Keel admin changes their
            # role, or when the user renames themselves on Keel. We also
            # cover the freshly-linked case (pre-existing local user just
            # connected to its Keel SocialAccount on this request) — without
            # this, fields like ``avatar_url`` stay blank until the user
            # logs in a *second* time, which is how Beacon/Yeoman ended up
            # showing initials instead of the uploaded avatar.
            if sociallogin.user and sociallogin.user.pk:
                u = sociallogin.user
                User = get_user_model()

                # --- Identity fields ---------------------------------------
                # Compute the full set of changes first so we can do one
                # UPDATE and avoid partial-write races.
                identity_updates = {}
                if preferred and u.username != preferred:
                    identity_updates['username'] = preferred
                if email and u.email != email:
                    identity_updates['email'] = email
                given = claims.get('given_name') or ''
                family = claims.get('family_name') or ''
                if given and u.first_name != given:
                    identity_updates['first_name'] = given
                if family and u.last_name != family:
                    identity_updates['last_name'] = family
                if hasattr(u, 'is_state_user'):
                    state_flag = bool(claims.get('is_state_user'))
                    if u.is_state_user != state_flag:
                        identity_updates['is_state_user'] = state_flag
                if hasattr(u, 'timezone'):
                    tz = claims.get('zoneinfo')
                    if tz is not None and u.timezone != tz:
                        identity_updates['timezone'] = tz
                if hasattr(u, 'locale'):
                    loc = claims.get('locale')
                    if loc is not None and u.locale != loc:
                        identity_updates['locale'] = loc
                if hasattr(u, 'avatar_url'):
                    pic = claims.get('picture')
                    if pic is not None and u.avatar_url != pic:
                        identity_updates['avatar_url'] = pic

                if identity_updates:
                    try:
                        User.objects.filter(pk=u.pk).update(**identity_updates)
                        for k, v in identity_updates.items():
                            setattr(u, k, v)
                        logger.debug(
                            'SSO: synced identity fields %s for user=%s',
                            list(identity_updates), u.pk,
                        )
                    except Exception:
                        logger.exception(
                            'SSO: Failed to sync identity fields for user=%s',
                            u.pk,
                        )

                # --- ProductAccess rows ------------------------------------
                # Driven by SYNCED_FIELDS so adding a field to
                # ProductAccess only requires updating the registry, not
                # this site and ``save_user`` separately.
                _mirror_product_access(u, claims)

                # One-shot AI-key hydration for local-AI-key products.
                # Existing/returning (and freshly-linked) users have a pk
                # here; new users are handled in save_user. Uses the
                # in-memory login token; persists nothing but the key.
                _maybe_hydrate_local_ai_key(sociallogin)
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
            # Always use preferred_username from the Keel JWT as the
            # canonical username. Allauth's default populate_user derives
            # a username from given_name+family_name ("Dan OKeefe" → "dan"),
            # which collides with existing users on repeated sign-ins and
            # spawns dan/dan1/dan2/dan3 zombies as the collision resolver
            # deconflicts. We override that here so every product agrees
            # with Keel on who the user is.
            preferred = (claims.get('preferred_username') or '').strip()
            if preferred:
                user.username = preferred
            elif not user.username:
                base = (email.split('@')[0] if email else 'user').lower().replace('.', '_')
                user.username = base
            if hasattr(user, 'is_state_user'):
                user.is_state_user = bool(claims.get('is_state_user'))
            # Mirror display preferences from Keel so the product's local
            # user row reflects the same timezone/locale the user picked
            # on Keel's profile panel. ``zoneinfo`` is the standard OIDC
            # claim name; ``locale`` is also OIDC-standard.
            zoneinfo_claim = claims.get('zoneinfo')
            if zoneinfo_claim is not None and hasattr(user, 'timezone'):
                user.timezone = zoneinfo_claim or ''
            locale_claim = claims.get('locale')
            if locale_claim is not None and hasattr(user, 'locale'):
                user.locale = locale_claim or ''
            # Mirror Keel's avatar URL into ``user.avatar_url`` so the
            # product's templates can render the same image without
            # uploading or storing the file locally. ``user.avatar`` (the
            # uploaded ImageField) takes precedence in ``get_avatar_url``,
            # but suite-mode products never have a local upload — only
            # the mirror.
            picture_claim = claims.get('picture')
            if picture_claim is not None and hasattr(user, 'avatar_url'):
                user.avatar_url = picture_claim or ''
            # Resolve role for the current product from the product_access claim
            product = get_product_code()
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

        current_product = get_product_code()

        # --- Keel OIDC path: mirror the full product_access claim --------
        if _is_keel_provider(sociallogin):
            claims = _extract_keel_claims(sociallogin)
            _mirror_product_access(user, claims)
            # New user's first login: hydrate the local AI key from Keel
            # with the in-memory login token (local-AI-key products only).
            _maybe_hydrate_local_ai_key(sociallogin)
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
