"""Regression guard: clicking a notification must reach the record.

History: the inbox row put ``href`` and ``hx-post`` on the same anchor.
htmx's ``shouldCancel()`` returns true for any ``<a href>`` it handles whose
href isn't a bare fragment, so every click fired the mark-read POST and
called ``preventDefault()`` — the user saw nothing happen. Rows now link at
``keel_notifications:open``, which marks read server-side and redirects.
"""
from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

LIST_URL = '/keel/notifications/'

# The manifest storage isn't built during the test run; render with the
# plain backend so {% static %} doesn't blow up on a missing entry.
_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}


@pytest.fixture
def user(db):
    from keel.accounts.models import Organization

    User = get_user_model()
    org = Organization.objects.get(slug='docklabs-internal')
    return User.objects.create_user(
        username='notif-open',
        email='notif-open@example.com',
        password='x',
        organization=org,
    )


def _notification(user, **kwargs):
    from keel.accounts.models import Notification

    return Notification.objects.create(
        recipient=user,
        title=kwargs.pop('title', 'Invitation assigned'),
        message=kwargs.pop('message', 'Body'),
        link=kwargs.pop('link', '/invitations/abc/'),
        **kwargs,
    )


def test_open_marks_read_and_redirects_to_link(client, user):
    notif = _notification(user)
    client.force_login(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp.status_code == 302
    assert resp['Location'] == '/invitations/abc/'
    notif.refresh_from_db()
    assert notif.is_read is True
    assert notif.read_at is not None


@pytest.mark.parametrize('link', ['', '   '])
def test_open_without_a_usable_link_falls_back_to_the_inbox(client, user, link):
    """Blank and whitespace-only both resolve to "no target" — the second
    only becomes falsy after .strip()."""
    notif = _notification(user, link=link)
    client.force_login(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp.status_code == 302
    assert resp['Location'] == LIST_URL
    notif.refresh_from_db()
    assert notif.is_read is True


@pytest.mark.parametrize('link', [
    'https://evil.example.com/steal',
    '//evil.example.com/steal',
    'javascript:alert(1)',
])
def test_open_refuses_offsite_links(client, user, link):
    notif = _notification(user, link=link)
    client.force_login(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp.status_code == 302
    assert resp['Location'] == LIST_URL


@override_settings(KEEL_FLEET_PRODUCTS=[
    {'name': 'Harbor', 'code': 'harbor', 'url': 'https://harbor.docklabs.ai/dashboard/'},
])
def test_open_allows_fleet_peer_deep_links(client, user):
    notif = _notification(user, link='https://harbor.docklabs.ai/applications/7/')
    client.force_login(user)

    resp = client.get(
        reverse('keel_notifications:open', args=[notif.pk]), secure=True,
    )

    assert resp.status_code == 302
    assert resp['Location'] == 'https://harbor.docklabs.ai/applications/7/'


def test_open_is_scoped_to_the_recipient(client, user):
    from keel.accounts.models import Organization

    User = get_user_model()
    other = User.objects.create_user(
        username='notif-open-other',
        email='notif-open-other@example.com',
        password='x',
        organization=Organization.objects.get(slug='docklabs-internal'),
    )
    notif = _notification(other)
    client.force_login(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp.status_code == 404


@override_settings(STORAGES=_STORAGES)
def test_inbox_row_links_at_open_and_carries_no_hx_post(client, user):
    """The anchor must not regain hx-post — that is the bug this guards."""
    notif = _notification(user)
    client.force_login(user)

    html = client.get(LIST_URL).content.decode()
    open_url = reverse('keel_notifications:open', args=[notif.pk])

    # Match the whole opening tag regardless of attribute order — the
    # invariant is "href points at open_url and carries no hx-post", not
    # which attribute happens to come first.
    anchor = next(
        (tag for tag in re.findall(r'<a\b[^>]*>', html)
         if f'href="{open_url}"' in tag),
        None,
    )
    assert anchor, f'inbox row does not link at {open_url}'
    assert 'hx-post' not in anchor


# ---------------------------------------------------------------------------
# Coverage gaps found by the ship coverage audit (2026-09-04)
# ---------------------------------------------------------------------------

def test_open_requires_login(client, user):
    """@login_required guards the route — anonymous never marks anything read."""
    notif = _notification(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp.status_code == 302
    assert 'login' in resp['Location']
    notif.refresh_from_db()
    assert notif.is_read is False


def test_open_is_idempotent_on_an_already_read_notification(client, user):
    """Re-opening must not clobber the original read_at timestamp."""
    from django.utils import timezone

    earlier = timezone.now() - timezone.timedelta(days=3)
    notif = _notification(user, is_read=True, read_at=earlier)
    client.force_login(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp.status_code == 302
    assert resp['Location'] == '/invitations/abc/'
    notif.refresh_from_db()
    assert notif.is_read is True
    assert notif.read_at == earlier


def test_open_marks_read_even_when_the_link_is_rejected(client, user):
    """The read side-effect happens before the target is vetted."""
    notif = _notification(user, link='https://evil.example.com/steal')
    client.force_login(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp['Location'] == LIST_URL
    notif.refresh_from_db()
    assert notif.is_read is True
    assert notif.read_at is not None


@override_settings(KEEL_FLEET_PRODUCTS=[
    {'name': 'Harbor', 'code': 'harbor', 'url': 'https://harbor.docklabs.ai/dashboard/'},
])
def test_open_refuses_an_http_downgrade_to_a_fleet_host(client, user):
    """A secure request must not be redirected to plain http, even on an
    allowed host — require_https tracks request.is_secure()."""
    notif = _notification(user, link='http://harbor.docklabs.ai/applications/7/')
    client.force_login(user)

    resp = client.get(
        reverse('keel_notifications:open', args=[notif.pk]), secure=True,
    )

    assert resp['Location'] == LIST_URL


def test_open_allows_an_absolute_same_host_link_over_plain_http(client, user):
    """On an insecure request require_https is False, so an absolute http
    link to the current host resolves rather than being dropped."""
    notif = _notification(user, link='http://testserver/invitations/abc/')
    client.force_login(user)

    resp = client.get(reverse('keel_notifications:open', args=[notif.pk]))

    assert resp['Location'] == 'http://testserver/invitations/abc/'


@override_settings(KEEL_FLEET_PRODUCTS=[
    None,
    'not-a-dict',
    {},
    {'url': None},
    {'name': 'No URL', 'code': 'nourl'},
    {'name': 'Harbor', 'code': 'harbor', 'url': 'https://harbor.docklabs.ai/dashboard/'},
])
def test_allowed_hosts_survives_a_malformed_fleet_list(client, user):
    """A junk KEEL_FLEET_PRODUCTS entry must not 500 the route — the good
    entry is still honored and the bad ones are skipped."""
    notif = _notification(user, link='https://harbor.docklabs.ai/applications/7/')
    client.force_login(user)

    resp = client.get(
        reverse('keel_notifications:open', args=[notif.pk]), secure=True,
    )

    assert resp.status_code == 302
    assert resp['Location'] == 'https://harbor.docklabs.ai/applications/7/'


@override_settings(STORAGES=_STORAGES)
def test_inbox_row_without_a_link_renders_no_anchor(client, user):
    """A linkless notification degrades to plain text, not a dead anchor."""
    notif = _notification(user, link='', title='CLICKTEST linkless')
    client.force_login(user)

    html = client.get(LIST_URL).content.decode()
    open_url = reverse('keel_notifications:open', args=[notif.pk])

    assert 'CLICKTEST linkless' in html
    assert open_url not in html
