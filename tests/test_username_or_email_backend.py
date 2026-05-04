"""Tests for keel.accounts.backends.UsernameOrEmailBackend.

Covers the contract advertised by the shared LoginForm: a user can sign in
by typing either their username OR their email address into the single
"Username or email" field.
"""
import pytest

from keel.accounts.backends import UsernameOrEmailBackend
from keel.accounts.models import KeelUser


@pytest.fixture
def user(db):
    return KeelUser.objects.create_user(
        username='alice',
        email='Alice@Example.com',
        password='correct-horse-battery-staple',
    )


@pytest.mark.django_db
def test_authenticates_by_username(user):
    backend = UsernameOrEmailBackend()
    assert backend.authenticate(None, username='alice', password='correct-horse-battery-staple') == user


@pytest.mark.django_db
def test_authenticates_by_email_case_insensitive(user):
    backend = UsernameOrEmailBackend()
    # Stored mixed-case; user types lowercase.
    assert backend.authenticate(None, username='alice@example.com', password='correct-horse-battery-staple') == user


@pytest.mark.django_db
def test_authenticates_by_email_exact_case(user):
    backend = UsernameOrEmailBackend()
    assert backend.authenticate(None, username='Alice@Example.com', password='correct-horse-battery-staple') == user


@pytest.mark.django_db
def test_wrong_password_returns_none(user):
    backend = UsernameOrEmailBackend()
    assert backend.authenticate(None, username='alice', password='wrong') is None
    assert backend.authenticate(None, username='alice@example.com', password='wrong') is None


@pytest.mark.django_db
def test_unknown_user_returns_none(db):
    backend = UsernameOrEmailBackend()
    assert backend.authenticate(None, username='nobody@nowhere.test', password='whatever') is None


@pytest.mark.django_db
def test_inactive_user_rejected(user):
    user.is_active = False
    user.save(update_fields=['is_active'])
    backend = UsernameOrEmailBackend()
    assert backend.authenticate(None, username='alice', password='correct-horse-battery-staple') is None
    assert backend.authenticate(None, username='alice@example.com', password='correct-horse-battery-staple') is None


@pytest.mark.django_db
def test_username_match_wins_over_email_collision(db):
    # Edge case: bob's username happens to equal carol's email.
    bob = KeelUser.objects.create_user(username='shared@example.com', email='bob@example.com', password='bob-pass')
    KeelUser.objects.create_user(username='carol', email='shared@example.com', password='carol-pass')
    backend = UsernameOrEmailBackend()
    # Typing the colliding string + bob's password should authenticate bob, not silently
    # try carol's email branch.
    assert backend.authenticate(None, username='shared@example.com', password='bob-pass') == bob
