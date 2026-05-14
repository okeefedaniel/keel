"""keel.mentions — suite-wide @-mentions on internal notes.

Public API (re-exported here so integrators have one import path):

    from keel.mentions import (
        MentionableTextarea,
        MentionFormMixin,
        MentionDelivery,
        parse_mentions,
        resolve_users,
        resolve_contacts,
    )

See ``keel/mentions/README.md`` for the integration guide.
"""
from __future__ import annotations

default_app_config = 'keel.mentions.apps.KeelMentionsConfig'


def __getattr__(name):
    # Lazy re-exports — avoid importing Django models at package import time
    # so this file is safe to import before Django settings are configured.
    if name == 'MentionableTextarea':
        from .widgets import MentionableTextarea as obj
        return obj
    if name == 'MentionFormMixin':
        from .forms import MentionFormMixin as obj
        return obj
    if name == 'MentionDelivery':
        from .models import MentionDelivery as obj
        return obj
    if name == 'parse_mentions':
        from .parser import parse_mentions as obj
        return obj
    if name == 'resolve_users':
        from .parser import resolve_users as obj
        return obj
    if name == 'resolve_contacts':
        from .parser import resolve_contacts as obj
        return obj
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
