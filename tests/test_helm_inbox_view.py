"""Tests for keel.feed.views.helm_inbox_view — the per-user inbox decorator.

Pins the security-critical bits:
- Bearer auth required; 401 on missing/wrong; 503 when unconfigured.
- Per-user-per-path cache key — user A NEVER sees user B's payload.
- Unknown user_sub returns 200 with empty items[] (not 404), so the
  Helm aggregator can render a clean "no items" badge.
- Missing ?user_sub= returns 400.
"""
import pytest

# allauth is an optional [sso] extra in keel; skip the whole module when
# the host environment doesn't have it. Products that consume keel.feed
# always install allauth via the [sso] extra, so this only matters for
# the keel-internal pytest run.
SocialAccount = pytest.importorskip('allauth.socialaccount.models').SocialAccount

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from keel.feed.views import helm_inbox_view, resolve_user_from_sub

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def _build_inbox_returning(items):
    """Make a wrapped view whose build returns the given items list."""
    @helm_inbox_view
    def view(request, user):
        return {
            'product': 'testprod', 'product_label': 'TestProd',
            'product_url': 'https://test/', 'user_sub': '',
            'items': items, 'unread_notifications': [], 'fetched_at': '',
        }
    return view


@pytest.mark.django_db
@override_settings(HELM_FEED_API_KEY='k', DEMO_MODE=False)
def test_missing_auth_returns_401():
    rf = RequestFactory()
    view = _build_inbox_returning([])
    resp = view(rf.get('/api/v1/helm-feed/inbox/?user_sub=x'))
    assert resp.status_code == 401


@pytest.mark.django_db
@override_settings(HELM_FEED_API_KEY='', DEMO_MODE=False)
def test_unconfigured_returns_503():
    rf = RequestFactory()
    view = _build_inbox_returning([])
    resp = view(rf.get('/api/v1/helm-feed/inbox/?user_sub=x',
                       HTTP_AUTHORIZATION='Bearer anything'))
    assert resp.status_code == 503


@pytest.mark.django_db
@override_settings(HELM_FEED_API_KEY='k', DEMO_MODE=False)
def test_missing_user_sub_returns_400():
    rf = RequestFactory()
    view = _build_inbox_returning([])
    resp = view(rf.get('/api/v1/helm-feed/inbox/', HTTP_AUTHORIZATION='Bearer k'))
    assert resp.status_code == 400


@pytest.mark.django_db
@override_settings(HELM_FEED_API_KEY='k', DEMO_MODE=False)
def test_unknown_sub_returns_empty_inbox():
    rf = RequestFactory()
    view = _build_inbox_returning([{'id': 'x', 'type': 'review',
                                    'title': 't', 'deep_link': '',
                                    'waiting_since': '', 'priority': 'normal'}])
    resp = view(rf.get('/api/v1/helm-feed/inbox/?user_sub=ghost',
                       HTTP_AUTHORIZATION='Bearer k'))
    assert resp.status_code == 200
    body = resp.json()
    assert body['items'] == []
    assert body['user_sub'] == 'ghost'


@pytest.mark.django_db
@override_settings(HELM_FEED_API_KEY='k', DEMO_MODE=False)
def test_per_user_cache_isolation():
    """User B must never see user A's cached payload."""
    u1 = User.objects.create_user(username='u1', email='u1@t.local')
    u2 = User.objects.create_user(username='u2', email='u2@t.local')
    SocialAccount.objects.create(user=u1, provider='keel', uid='sub1')
    SocialAccount.objects.create(user=u2, provider='keel', uid='sub2')

    @helm_inbox_view
    def view(request, user):
        return {
            'product': 'p', 'product_label': 'P', 'product_url': '',
            'user_sub': '', 'items': [{'id': str(user.pk), 'type': 'review',
                                       'title': user.username, 'deep_link': '',
                                       'waiting_since': '', 'priority': 'normal'}],
            'unread_notifications': [], 'fetched_at': '',
        }

    rf = RequestFactory()
    r1 = view(rf.get('/api/v1/helm-feed/inbox/?user_sub=sub1',
                     HTTP_AUTHORIZATION='Bearer k'))
    r2 = view(rf.get('/api/v1/helm-feed/inbox/?user_sub=sub2',
                     HTTP_AUTHORIZATION='Bearer k'))

    assert r1.json()['items'][0]['title'] == 'u1'
    assert r2.json()['items'][0]['title'] == 'u2'


@pytest.mark.django_db
def test_resolve_user_from_sub_finds_keel_socialaccount():
    u = User.objects.create_user(username='x', email='x@t.local')
    SocialAccount.objects.create(user=u, provider='keel', uid='abc')
    assert resolve_user_from_sub('abc') == u
    assert resolve_user_from_sub('') is None
    assert resolve_user_from_sub('not-a-real-sub') is None
