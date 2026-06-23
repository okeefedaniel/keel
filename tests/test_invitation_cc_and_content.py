"""Tests for the invitation CC address and the beta / AI email sections.

Covers three additions to ``send_invitation``:

1. An optional ``cc_email`` is validated, persisted on every Invitation row
   in the batch, and added to the outgoing email's CC list.
2. A batch granting beta-tester status renders the "you're a beta tester /
   send feedback via the bottom-right chat" section.
3. A batch granting AI access renders the bring-your-own Anthropic API key
   walkthrough.

Neither section appears when its flag is absent.
"""

from __future__ import annotations

import pytest
from django.core import mail

from keel.accounts.models import (
    Invitation, KeelUser, Organization, OrganizationProductSubscription,
)


pytest.importorskip('cryptography')


@pytest.fixture
def admin_user(db):
    org = Organization.objects.create(slug='cc-test-org', name='CC Test')
    OrganizationProductSubscription.objects.create(
        organization=org, product='beacon', is_active=True, ai_enabled=True,
    )
    u = KeelUser.objects.create(
        username='cc-inviter', email='cc-inviter@example.test',
        organization=org, is_staff=True, is_superuser=True,
    )
    return u


@pytest.fixture
def client(admin_user):
    from django.test import Client
    c = Client()
    c.force_login(admin_user)
    return c


def test_cc_email_persisted_and_added_to_message(db, client):
    resp = client.post('/keel/accounts/invitations/send/', {
        'email': 'invitee@example.test',
        'cc_email': 'Watcher@Example.Test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
    })
    assert resp.status_code in (200, 302)

    inv = Invitation.objects.get(email='invitee@example.test', product='beacon')
    assert inv.cc_email == 'watcher@example.test'  # normalized to lower

    assert len(mail.outbox) == 1
    assert mail.outbox[0].cc == ['watcher@example.test']
    assert mail.outbox[0].to == ['invitee@example.test']


def test_invalid_cc_email_rejected_no_invite_created(db, client):
    resp = client.post('/keel/accounts/invitations/send/', {
        'email': 'invitee2@example.test',
        'cc_email': 'not-an-email',
        'products': ['beacon'],
        'role__beacon': 'analyst',
    })
    assert resp.status_code in (200, 302)
    assert not Invitation.objects.filter(email='invitee2@example.test').exists()
    assert mail.outbox == []


def test_no_cc_means_empty_cc_list(db, client):
    resp = client.post('/keel/accounts/invitations/send/', {
        'email': 'invitee3@example.test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
    })
    assert resp.status_code in (200, 302)
    inv = Invitation.objects.get(email='invitee3@example.test', product='beacon')
    assert inv.cc_email == ''
    assert len(mail.outbox) == 1
    assert mail.outbox[0].cc == []


def test_beta_section_rendered_when_beta_granted(db, client):
    client.post('/keel/accounts/invitations/send/', {
        'email': 'beta@example.test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
        'beta__beacon': '1',
    })
    body = mail.outbox[0].body
    html = mail.outbox[0].alternatives[0][0]
    assert 'beta tester' in body.lower()
    assert 'bottom-right' in body
    assert 'beta tester' in html.lower()


def test_ai_section_rendered_when_ai_granted(db, client):
    client.post('/keel/accounts/invitations/send/', {
        'email': 'ai@example.test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
        'ai_enabled__beacon': '1',
    })
    body = mail.outbox[0].body
    html = mail.outbox[0].alternatives[0][0]
    assert 'sk-ant-' in body
    assert 'console.anthropic.com' in body
    assert 'sk-ant-' in html


def test_sections_absent_when_neither_flag_set(db, client):
    client.post('/keel/accounts/invitations/send/', {
        'email': 'plain@example.test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
    })
    body = mail.outbox[0].body
    assert 'beta tester' not in body.lower()
    assert 'sk-ant-' not in body


def test_ai_section_fallback_when_settings_url_unresolvable(db, client, monkeypatch):
    """When ``keel_settings:index`` doesn't resolve, ``ai_settings_url`` is ''
    and both the view's NoReverseMatch fallback and the template ``{% else %}``
    (plain "Settings -> AI" text, no link) are exercised."""
    import django.urls
    from django.urls import NoReverseMatch

    def _raise(*a, **k):
        raise NoReverseMatch('keel_settings:index not mounted')

    # send_invitation does `from django.urls import ... reverse` at call time,
    # which rebinds to whatever django.urls.reverse is then — patch the source.
    monkeypatch.setattr(django.urls, 'reverse', _raise)

    client.post('/keel/accounts/invitations/send/', {
        'email': 'ai-fallback@example.test',
        'products': ['beacon'],
        'role__beacon': 'analyst',
        'ai_enabled__beacon': '1',
    })
    body = mail.outbox[0].body
    html = mail.outbox[0].alternatives[0][0]
    # AI section still renders, but with the no-link fallback wording.
    assert 'sk-ant-' in body
    assert 'Settings -> AI' in body
    assert 'Settings &rarr; AI' in html


def test_multi_product_batch_cc_and_flags(db, admin_user, client):
    """A batch spanning two products: cc_email lands on every Invitation row,
    and the beta/AI sections render off the batch-wide any() even though only
    one product in the batch carries each flag (beta on beacon, AI on harbor)."""
    # admin_user's org subscribes beacon (ai on); add harbor (ai on) too.
    OrganizationProductSubscription.objects.create(
        organization=admin_user.organization, product='harbor',
        is_active=True, ai_enabled=True,
    )

    resp = client.post('/keel/accounts/invitations/send/', {
        'email': 'batch@example.test',
        'cc_email': 'batchwatcher@example.test',
        'products': ['beacon', 'harbor'],
        'role__beacon': 'analyst',
        'role__harbor': 'reviewer',
        'beta__beacon': '1',          # beta on beacon only
        'ai_enabled__harbor': '1',    # AI on harbor only
    })
    assert resp.status_code in (200, 302)

    invites = Invitation.objects.filter(email='batch@example.test')
    assert invites.count() == 2
    # cc_email recorded on every row in the batch.
    assert all(inv.cc_email == 'batchwatcher@example.test' for inv in invites)
    # exactly one beta, one AI — proves the flags are per-row, not blanket.
    assert invites.filter(is_beta_tester=True).count() == 1
    assert invites.filter(ai_enabled=True).count() == 1

    assert len(mail.outbox) == 1
    assert mail.outbox[0].cc == ['batchwatcher@example.test']
    body = mail.outbox[0].body
    # Both sections render because any() is True across the batch.
    assert 'beta tester' in body.lower()
    assert 'sk-ant-' in body
