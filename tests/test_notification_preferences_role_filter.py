"""Tests for the role-eligibility filter in the notification preferences UI.

Pins the contract that ``get_types_by_category(for_user=...)`` only
surfaces notification types a user could plausibly receive given their
``ProductAccess`` rows for the current product (``KEEL_PRODUCT_CODE``).

Background: pre-fix, the preferences page enumerated every registered
type, which leaked admin-only notification keys into non-admin users'
preferences pages and let them toggle SMS for events they would never
receive.
"""
import pytest
from django.test import override_settings


@pytest.fixture(autouse=True)
def isolated_registry():
    """Snapshot + restore the global registry around each test.

    The keel notification registry is module-global; tests register
    bespoke types and must clean up so unrelated suites don't see them.
    """
    from keel.notifications import registry

    saved = dict(registry._registry)
    registry._registry.clear()
    try:
        yield registry
    finally:
        registry._registry.clear()
        registry._registry.update(saved)


@pytest.fixture
def types(isolated_registry):
    """Register a representative slice: admin-only, all, role-scoped, internal,
    resolver-only, and an unreachable empty-roles type."""
    from keel.notifications.registry import NotificationType, register

    register(NotificationType(
        key='admin_only_alert',
        label='Admin Only Alert',
        category='Test',
        default_roles=['system_admin', 'agency_admin'],
    ))
    register(NotificationType(
        key='analyst_alert',
        label='Analyst Alert',
        category='Test',
        default_roles=['analyst'],
    ))
    register(NotificationType(
        key='everyone_alert',
        label='Everyone Alert',
        category='Test',
        default_roles=['all'],
    ))
    register(NotificationType(
        key='internal_confirmation',
        label='Internal SMS Confirmation',
        category='Test',
        default_roles=['all'],
        internal=True,
    ))
    register(NotificationType(
        key='record_owner_alert',
        label='Record Owner Alert',
        category='Test',
        default_roles=[],
        recipient_resolver=lambda ctx: [],
    ))
    register(NotificationType(
        key='unreachable_alert',
        label='Unreachable Alert',
        category='Test',
        default_roles=[],
        recipient_resolver=None,
    ))


@pytest.fixture
def analyst_user(db):
    from keel.accounts.models import KeelUser, ProductAccess

    user = KeelUser.objects.create_user(
        username='analyst-jane', email='jane@example.com', password='x',
    )
    ProductAccess.objects.create(
        user=user, product='keel', role='analyst', is_active=True,
    )
    return user


@pytest.fixture
def admin_user(db):
    from keel.accounts.models import KeelUser, ProductAccess

    user = KeelUser.objects.create_user(
        username='admin-bob', email='bob@example.com', password='x',
    )
    ProductAccess.objects.create(
        user=user, product='keel', role='system_admin', is_active=True,
    )
    return user


@pytest.fixture
def superuser(db):
    from keel.accounts.models import KeelUser

    return KeelUser.objects.create_user(
        username='dokadmin-test', email='dok@example.com', password='x',
        is_superuser=True, is_staff=True,
    )


def _flat_keys(types_by_category):
    return {nt.key for cat in types_by_category.values() for nt in cat}


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_regular_user_sees_only_eligible_and_all(types, analyst_user):
    from keel.notifications.registry import get_types_by_category

    keys = _flat_keys(get_types_by_category(for_user=analyst_user))
    assert keys == {'analyst_alert', 'everyone_alert'}


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_admin_user_sees_admin_types(types, admin_user):
    from keel.notifications.registry import get_types_by_category

    keys = _flat_keys(get_types_by_category(for_user=admin_user))
    assert 'admin_only_alert' in keys
    assert 'everyone_alert' in keys
    # An admin without the analyst role still doesn't get analyst-only types.
    assert 'analyst_alert' not in keys


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_superuser_sees_everything_except_internal(types, superuser):
    from keel.notifications.registry import get_types_by_category

    keys = _flat_keys(get_types_by_category(for_user=superuser))
    # Superusers bypass role gating but still respect the internal flag.
    assert 'admin_only_alert' in keys
    assert 'analyst_alert' in keys
    assert 'everyone_alert' in keys
    assert 'record_owner_alert' in keys
    assert 'unreachable_alert' in keys
    assert 'internal_confirmation' not in keys


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_internal_types_hidden_from_all(types, analyst_user, admin_user):
    from keel.notifications.registry import get_types_by_category

    for user in (analyst_user, admin_user):
        keys = _flat_keys(get_types_by_category(for_user=user))
        assert 'internal_confirmation' not in keys


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_resolver_only_types_hidden_by_default(types, analyst_user):
    from keel.notifications.registry import get_types_by_category

    keys = _flat_keys(get_types_by_category(for_user=analyst_user))
    assert 'record_owner_alert' not in keys
    assert 'unreachable_alert' not in keys


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_resolver_only_types_returned_when_explicitly_included(
    types, analyst_user,
):
    from keel.notifications.registry import get_types_by_category

    keys = _flat_keys(get_types_by_category(
        for_user=analyst_user, include_resolver_only=True,
    ))
    assert 'record_owner_alert' in keys
    # An empty-roles type with NO resolver is still unreachable; even
    # the include_resolver_only flag won't bring it back for end users.
    assert 'unreachable_alert' not in keys


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_no_for_user_returns_full_registry_for_admin_surfaces(types):
    """The admin matrix in keel_site/notifications_admin.py relies on
    the no-arg call returning every (non-internal) type."""
    from keel.notifications.registry import get_types_by_category

    keys = _flat_keys(get_types_by_category())
    assert {
        'admin_only_alert', 'analyst_alert', 'everyone_alert',
        'record_owner_alert', 'unreachable_alert',
    } <= keys
    assert 'internal_confirmation' not in keys
    keys_with_internal = _flat_keys(
        get_types_by_category(include_internal=True),
    )
    assert 'internal_confirmation' in keys_with_internal


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_inactive_product_access_does_not_grant_visibility(types, db):
    from keel.accounts.models import KeelUser, ProductAccess
    from keel.notifications.registry import get_types_by_category

    user = KeelUser.objects.create_user(
        username='ex-admin', email='ex@example.com', password='x',
    )
    ProductAccess.objects.create(
        user=user, product='keel', role='system_admin', is_active=False,
    )
    keys = _flat_keys(get_types_by_category(for_user=user))
    assert 'admin_only_alert' not in keys
    # The 'all' bucket still passes for any authenticated user.
    assert 'everyone_alert' in keys


@override_settings(KEEL_PRODUCT_CODE='keel')
def test_other_product_access_does_not_grant_visibility(types, db):
    from keel.accounts.models import KeelUser, ProductAccess
    from keel.notifications.registry import get_types_by_category

    user = KeelUser.objects.create_user(
        username='harbor-admin', email='ha@example.com', password='x',
    )
    # system_admin on harbor does not confer admin visibility on keel.
    ProductAccess.objects.create(
        user=user, product='harbor', role='system_admin', is_active=True,
    )
    keys = _flat_keys(get_types_by_category(for_user=user))
    assert 'admin_only_alert' not in keys
