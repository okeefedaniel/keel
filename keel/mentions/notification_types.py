"""Register the ``note_mentioned`` notification type.

Owned by keel.mentions (not keel.notifications.product_types) so the
type only appears in the registry when this module is installed.
"""
from __future__ import annotations

from keel.notifications.registry import NotificationType, register


def register_mention_types():
    register(NotificationType(
        key='note_mentioned',
        label='Mentioned in a note',
        description='Someone @-mentioned you in a note or comment.',
        category='Collaboration',
        default_channels=['in_app', 'email'],
        default_roles=['all'],   # any authenticated user may receive
        priority='medium',
        email_template='keel/mentions/emails/note_mentioned.html',
        email_subject='{actor_name} mentioned you on "{record_title}"',
        link_template='{source_url}',
        allow_mute=True,
        internal=False,
    ))
