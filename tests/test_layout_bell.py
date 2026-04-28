"""Regression guard: the topbar bell must link to the notifications list,
not the dead `#` anchor.

The default lives in keel/core/templates/keel/layouts/app.html (and the
duplicate fragment in keel/core/templates/keel/components/topbar.html).
History: 5 of 9 DockLabs products forgot to override the
`notifications_url` block, leaving the bell as `href="#"`. The default
was changed to auto-resolve `keel_notifications:list` so missing the
override no longer produces a dead link.
"""
from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, override_settings


@pytest.fixture
def auth_request(db):
    User = get_user_model()
    user = User.objects.create_user(
        username='bell-test',
        email='bell-test@example.com',
        password='x',
    )
    req = RequestFactory().get('/')
    req.user = user
    return req


def _render_layout_bell(request):
    """Render the bell fragment from keel/layouts/app.html.

    Use a child template that {% extends %} the layout so block
    inheritance and the {% url … as %} guard run exactly as in production.
    """
    tpl = Template(
        '{% extends "keel/layouts/app.html" %}'
        '{% block content %}content{% endblock %}'
    )
    return tpl.render(Context({'request': request, 'user': request.user}))


def _bell_href(html):
    """Extract the href from the topbar bell anchor (icon-btn + bi-bell).

    The user dropdown also contains a `bi-bell` for the preferences link;
    we want the topbar bell specifically, which has `class="icon-btn"`.
    """
    match = re.search(
        r'<a class="icon-btn"[^>]*href="([^"]*)"[^>]*title="Notifications"',
        html,
    )
    assert match, 'topbar bell anchor not found in rendered layout'
    return match.group(1)


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
def test_layout_bell_resolves_to_notifications_list(auth_request):
    href = _bell_href(_render_layout_bell(auth_request))
    assert href != '#', (
        'bell href is `#` — products that forget to override the '
        '`notifications_url` block will ship a dead bell link. '
        'Default should auto-resolve `keel_notifications:list`.'
    )
    assert href.endswith('/notifications/'), (
        f'bell href is {href!r}; expected to end with /notifications/'
    )
