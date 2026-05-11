"""Tests that ``KeelOIDCValidator`` emits the ``beta_products`` claim.

Beta-tester status is the gate for the feedback widget. Before keel 0.35.0
the flag never left Keel's DB — the OIDC validator only read
``(product, role)`` and the SSO adapter only wrote ``role`` + ``is_active``,
so a Keel admin ticking ``is_beta_tester`` on a user's ProductAccess row
had no observable effect on any product. This file pins the emit path.

The scope mapping itself is covered by
``test_oidc_validator_claim_scope.py``.
"""

from __future__ import annotations

import pytest

from keel.accounts.models import KeelUser, Organization, ProductAccess


pytest.importorskip('cryptography')
pytest.importorskip('oauth2_provider')


@pytest.fixture
def org(db):
    return Organization.objects.create(slug='beta-claims-org', name='Test')


def _request_for(user):
    class _Req:
        pass
    r = _Req()
    r.user = user
    return r


def test_emits_beta_products_for_beta_rows(db, org):
    """Every ``is_beta_tester=True`` active ProductAccess row appears in the claim."""
    from keel.oidc.validators import KeelOIDCValidator
    u = KeelUser.objects.create(
        username='beta-user', email='beta@example.test', organization=org,
    )
    ProductAccess.objects.create(
        user=u, product='beacon', role='analyst',
        is_active=True, is_beta_tester=True,
    )
    ProductAccess.objects.create(
        user=u, product='harbor', role='analyst',
        is_active=True, is_beta_tester=False,
    )

    claims = KeelOIDCValidator().get_additional_claims(_request_for(u))

    assert claims['beta_products'] == ['beacon']
    # product_access shape is unchanged — beta info is a separate claim.
    assert claims['product_access'] == {'beacon': 'analyst', 'harbor': 'analyst'}


def test_emits_empty_list_when_no_beta_rows(db, org):
    from keel.oidc.validators import KeelOIDCValidator
    u = KeelUser.objects.create(
        username='non-beta-user', email='nb@example.test', organization=org,
    )
    ProductAccess.objects.create(
        user=u, product='beacon', role='analyst',
        is_active=True, is_beta_tester=False,
    )

    claims = KeelOIDCValidator().get_additional_claims(_request_for(u))

    assert claims['beta_products'] == []


def test_inactive_beta_row_excluded(db, org):
    """A deactivated ProductAccess row must not leak into the claim."""
    from keel.oidc.validators import KeelOIDCValidator
    u = KeelUser.objects.create(
        username='ex-beta', email='ex@example.test', organization=org,
    )
    ProductAccess.objects.create(
        user=u, product='beacon', role='analyst',
        is_active=False, is_beta_tester=True,
    )

    claims = KeelOIDCValidator().get_additional_claims(_request_for(u))

    assert claims['beta_products'] == []
