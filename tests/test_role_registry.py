"""Tests for the suite-wide PRODUCT_ROLES role registry.

Pins the invariant that every customer-facing product registers an
``agency_admin`` role so a customer's point-of-contact admin always has
a place to land. Also pins the ROLE_LABELS humanization for the role.
"""
import pytest


# Products that MUST expose an `agency_admin` role. Matches the seven
# products this rollout retrofitted plus the two (beacon, harbor) that
# already had it. `keel` itself also registers it so a customer admin
# can manage their own org's users in the Keel admin console.
PRODUCTS_WITH_AGENCY_ADMIN = (
    'beacon', 'harbor', 'admiralty', 'manifest', 'lookout',
    'bounty', 'purser', 'helm', 'yeoman', 'keel',
)


@pytest.mark.parametrize('product', PRODUCTS_WITH_AGENCY_ADMIN)
def test_product_registers_agency_admin(product):
    from keel.accounts.models import PRODUCT_ROLES
    role_slugs = {slug for slug, _ in PRODUCT_ROLES[product]}
    assert 'agency_admin' in role_slugs, (
        f'{product} is missing the agency_admin role registration'
    )


def test_role_labels_humanizes_agency_admin():
    from keel.accounts.models import KeelUser
    assert KeelUser.ROLE_LABELS.get('agency_admin') == 'Agency Admin'


def test_protected_admin_roles_includes_agency_admin():
    from keel.accounts.services import PROTECTED_ADMIN_ROLES
    # The role we add MUST be in the protected set so an agency_admin
    # cannot peer-grant another agency_admin.
    assert 'agency_admin' in PROTECTED_ADMIN_ROLES
    # The IT-tier roles also stay protected.
    assert 'system_admin' in PROTECTED_ADMIN_ROLES
    assert 'admin' in PROTECTED_ADMIN_ROLES
