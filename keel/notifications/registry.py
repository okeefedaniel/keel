"""Notification type registry.

Products register their notification types at startup. The registry
provides a central catalog of all notification events, their default
channels, recipient roles, and templates.
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Global registry — populated by products during AppConfig.ready()
_registry: dict[str, 'NotificationType'] = {}


@dataclass
class NotificationType:
    """Definition of a notification event.

    Attributes:
        key: Unique identifier (e.g., 'application_submitted').
            Convention: '{entity}_{action}' using snake_case.
        label: Human-readable name for preferences UI.
        description: Longer description for preferences page.
        category: Grouping for the preferences UI (e.g., 'Applications',
            'FOIA', 'Grants'). Defaults to 'General'.
        default_channels: Channels enabled by default if user has no
            preference set. Options: 'in_app', 'email', 'sms'.
        default_roles: Roles that receive this notification by default.
            Use 'all' for all authenticated users.
            Products define their own role values.
        priority: Default priority level ('low', 'medium', 'high', 'urgent').
        email_template: Path to email template (HTML). A matching .txt
            template is auto-discovered for plain-text fallback.
        email_subject: Subject line template string. Can use {context} vars.
            If None, uses the notification title.
        recipient_resolver: Optional callable(event_context) -> list[User].
            When provided, overrides role-based resolution.
            Receives the full context dict passed to notify().
        link_template: URL path template for auto-generating the
            notification link from context. Uses Python str.format() syntax
            with dot-path resolution, e.g.:
                '/applications/{application.pk}/'
                '/awards/{award.pk}/amendments/{amendment.pk}/'
            Dot-paths are resolved from the context dict passed to notify().
            If the caller passes an explicit ``link`` kwarg, it takes
            precedence over link_template.
        agency_scoped: If True, role-based resolution filters by the
            agency associated with the context object.
        agency_field: Dot-path to extract agency from context for scoping.
            E.g., 'application.grant_program.agency' or 'award.agency'.
        allow_mute: Whether users can mute this notification type.
            Set False for critical system notifications.
        internal: If True, hide this type from the user-facing
            preferences UI. Use for system notifications the user does
            not opt into directly — e.g. an opt-in CONFIRMATION SMS that
            fires automatically when the user toggles SMS on for some
            other type. The user opts in elsewhere; this row only exists
            so the dispatch + log machinery has a notification key to
            attach the confirmation to. Default False.
    """
    key: str
    label: str
    description: str = ''
    category: str = 'General'
    default_channels: list[str] = field(default_factory=lambda: ['in_app', 'email'])
    default_roles: list[str] = field(default_factory=list)
    priority: str = 'medium'
    email_template: Optional[str] = None
    email_subject: Optional[str] = None
    recipient_resolver: Optional[Callable] = None
    link_template: Optional[str] = None
    agency_scoped: bool = False
    agency_field: str = ''
    allow_mute: bool = True
    internal: bool = False


def register(notification_type: NotificationType):
    """Register a notification type in the global registry.

    Call this in your product's AppConfig.ready() or in a dedicated
    notifications.py module that's imported during ready().

    Duplicate keys log a warning and overwrite the previous entry.
    """
    if notification_type.key in _registry:
        logger.warning(
            'Notification type %r re-registered (overwriting)',
            notification_type.key,
        )
    _registry[notification_type.key] = notification_type


def get_type(key: str) -> Optional[NotificationType]:
    """Look up a registered notification type by key."""
    return _registry.get(key)


def get_all_types() -> dict[str, NotificationType]:
    """Return all registered notification types."""
    return dict(_registry)


def get_types_by_category(
    *,
    include_internal: bool = False,
    for_user=None,
    include_resolver_only: bool = False,
) -> dict[str, list[NotificationType]]:
    """Return notification types grouped by category (for preferences UI).

    Filters applied (in order):

    - Internal types (``NotificationType.internal=True``) are excluded by
      default — they fire automatically in response to a user action and
      should not appear as togglable rows in the preferences table. Pass
      ``include_internal=True`` for admin / debug surfaces that need to
      enumerate the full registry.
    - When ``for_user`` is provided, types whose ``default_roles`` don't
      overlap any active ``ProductAccess.role`` the user holds for the
      current product (``KEEL_PRODUCT_CODE``) are excluded. This prevents
      role leak in the user-facing preferences UI: a non-admin user
      should not see admin-only notification types listed (they'd never
      receive them, and toggling an SMS channel for one would be
      misleading). Types with ``default_roles == ['all']`` always pass.
      Django superusers see every type.
    - When ``for_user`` is provided, types with empty ``default_roles``
      AND a ``recipient_resolver`` are HIDDEN by default — they are
      driven by explicit per-event context (e.g. "owner of this record")
      and a non-eligible user would never receive them. Pass
      ``include_resolver_only=True`` to include them anyway.
    """
    user_roles: set[str] | None = None
    is_superuser = False
    if for_user is not None and getattr(for_user, 'is_authenticated', False):
        is_superuser = bool(getattr(for_user, 'is_superuser', False))
        if not is_superuser:
            user_roles = _user_product_roles(for_user)

    by_cat: dict[str, list[NotificationType]] = {}
    for nt in _registry.values():
        if nt.internal and not include_internal:
            continue
        if for_user is not None and not _user_eligible_for_type(
            nt,
            user_roles=user_roles,
            is_superuser=is_superuser,
            include_resolver_only=include_resolver_only,
        ):
            continue
        by_cat.setdefault(nt.category, []).append(nt)
    return by_cat


def _user_product_roles(user) -> set[str]:
    """Return the user's active ProductAccess roles for the current product.

    Returns an empty set when the user has no access rows for this
    product — they should see no role-gated types. Defensive against
    missing settings or a user model without the expected reverse
    relation.
    """
    from django.conf import settings

    product = (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower()
    try:
        qs = user.product_access.filter(is_active=True)
        if product:
            qs = qs.filter(product=product)
        return set(qs.values_list('role', flat=True))
    except Exception:
        logger.debug(
            'Could not resolve product roles for user=%s', getattr(user, 'pk', None),
            exc_info=True,
        )
        return set()


def _user_eligible_for_type(
    nt: 'NotificationType',
    *,
    user_roles: set[str] | None,
    is_superuser: bool,
    include_resolver_only: bool,
) -> bool:
    """Decide whether a single type should appear in a user's preferences UI.

    Mirrors the spec used by ``dispatch._resolve_recipients`` at SEND
    time so the preferences table only lists rows the user could
    plausibly receive.
    """
    if is_superuser:
        return True
    # ``default_roles == ['all']`` is the explicit "anyone authenticated"
    # opt-in — it bypasses role gating at send time and should bypass it
    # in the preferences UI too.
    if 'all' in nt.default_roles:
        return True
    if not nt.default_roles:
        # Empty roles + resolver_only ⇒ explicit-context recipients
        # (e.g. record owner). Hidden by default to avoid misleading
        # users into toggling channels for events they'd never receive.
        if nt.recipient_resolver is not None:
            return include_resolver_only
        # Empty roles AND no resolver ⇒ unreachable / misconfigured.
        # Hide it from end users; admin surfaces use include_internal /
        # the full registry to surface these for cleanup.
        return False
    if user_roles is None:
        return False
    return bool(user_roles & set(nt.default_roles))


def apply_overrides():
    """Load persisted overrides from the database and patch the registry.

    Called once during AppConfig.ready(), after hardcoded types are registered.
    Silently skips if the database table doesn't exist yet (pre-migration).
    """
    try:
        from keel.accounts.models import NotificationTypeOverride
        for override in NotificationTypeOverride.objects.all():
            ntype = _registry.get(override.key)
            if ntype is None:
                continue
            if override.channels:
                ntype.default_channels = override.channels
            if override.roles:
                ntype.default_roles = override.roles
            if override.priority:
                ntype.priority = override.priority
            if override.allow_mute is not None:
                ntype.allow_mute = override.allow_mute
    except Exception:
        logger.debug('Could not load notification overrides (table may not exist yet)', exc_info=True)


def clear_registry():
    """Clear all registered types. Used in testing."""
    _registry.clear()
