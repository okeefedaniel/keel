"""ModelForm mixin that wires @-mention parsing + dispatch into save().

Usage:

    from keel.mentions import MentionFormMixin, MentionableTextarea

    class ApplicationCommentForm(MentionFormMixin, forms.ModelForm):
        class Meta:
            model = ApplicationComment
            fields = ['content', 'is_internal']
            widgets = {'content': MentionableTextarea()}

        # Required: tell the mixin what record this note hangs off so
        # cross-product mentions carry source_url + source_label.
        def get_mention_source(self):
            return self.instance.application  # the parent record

Override ``get_mention_source_url`` / ``get_mention_source_label`` if
they cannot be derived from ``get_mention_source()`` (default uses
``get_absolute_url()`` and ``str(source)``).
"""
from __future__ import annotations

import logging

from django.conf import settings

from .parser import MentionToken, parse_mentions, resolve_contacts, resolve_users

logger = logging.getLogger(__name__)

_DEFAULT_RECIPIENT_CAP = 25


def _recipient_cap() -> int:
    return int(getattr(settings, 'KEEL_MENTIONS_RECIPIENT_CAP', _DEFAULT_RECIPIENT_CAP))


def _current_product_code() -> str:
    return (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower()


class MentionFormMixin:
    """Parse mentions from ``content`` and dispatch on save.

    Lifecycle:

    1. ``save(commit=True)`` writes the row and calls Django's normal
       ``_save_m2m()``.
    2. Our ``_save_m2m()`` override:
       a. Calls super (writes the ``mentions`` M2M Django generated).
       b. Re-parses ``content`` and resolves users/contacts.
       c. Computes ``added_users`` and ``added_contacts`` vs the prior
          M2M state captured before super ran.
       d. Calls ``dispatch_mentions(...)`` for the added recipients only.

    Removing a mention by editing the note does NOT retract a delivered
    notification (once sent, sent). The local M2M and the
    ``MentionDelivery`` row remain for audit.
    """

    # Hook overridable by callers — see module docstring.
    def get_mention_source(self):
        """The parent record this note hangs off. Default: instance itself."""
        return self.instance

    def get_mention_source_url(self) -> str:
        source = self.get_mention_source()
        try:
            return source.get_absolute_url() or ''
        except Exception:
            return ''

    def get_mention_source_label(self) -> str:
        source = self.get_mention_source()
        return str(source) if source else ''

    def get_mention_author(self):
        """User author of the note. Defaults to ``instance.author``."""
        return getattr(self.instance, 'author', None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_added_recipients(self, content: str, author) -> tuple[list, list[dict]]:
        tokens = parse_mentions(content)
        usernames = [t.ref for t in tokens if t.kind == 'user']
        slugs = [t.ref for t in tokens if t.kind == 'contact']

        users = resolve_users(usernames, requester=author) if author else []
        contacts = resolve_contacts(slugs, requester=author) if (author and slugs) else []

        cap = _recipient_cap()
        total = len(users) + len(contacts)
        if total > cap:
            # Drop excess from the tail (preserve first-occurrence priority).
            keep_users = users[: min(len(users), cap)]
            remaining = max(0, cap - len(keep_users))
            keep_contacts = contacts[: remaining]
            logger.info(
                'MentionFormMixin: capped mentions %d → %d (note=%s)',
                total, cap, getattr(self.instance, 'pk', '?'),
            )
            return keep_users, keep_contacts
        return users, contacts

    def _save_m2m(self):
        """Override Django's M2M save hook to also dispatch mentions."""
        # Snapshot the prior M2M state BEFORE super writes the new one.
        prior_user_ids: set = set()
        if self.instance.pk is not None:
            try:
                prior_user_ids = set(
                    self.instance.mentions.values_list('pk', flat=True)
                )
            except Exception:
                prior_user_ids = set()

        # Snapshot prior contact deliveries for this note (for diff).
        prior_contact_slugs: set[str] = set()
        try:
            from django.contrib.contenttypes.models import ContentType
            from .models import MentionDelivery
            note_ct = ContentType.objects.get_for_model(type(self.instance))
            prior_contact_slugs = set(
                MentionDelivery.objects
                .filter(
                    note_content_type=note_ct,
                    note_object_id=self.instance.pk,
                    recipient_kind=MentionDelivery.KIND_CONTACT,
                )
                .values_list('recipient_ref', flat=True)
            )
        except Exception:
            prior_contact_slugs = set()

        # Resolve current mentions from the just-saved content.
        author = self.get_mention_author()
        content = (self.cleaned_data or {}).get('content', '') or getattr(
            self.instance, 'content', '',
        )
        resolved_users, resolved_contacts = self._resolve_added_recipients(
            content, author,
        )

        # Populate the ``mentions`` M2M (Django's super won't know about it
        # unless ``mentions`` is in Meta.fields; we set it directly).
        try:
            self.instance.mentions.set(resolved_users)
        except Exception:
            logger.exception(
                'MentionFormMixin: failed to set mentions M2M (note=%s)',
                getattr(self.instance, 'pk', '?'),
            )

        # Now run super so any product-declared M2Ms persist too.
        super()._save_m2m()

        # Diff and dispatch.
        added_users = [u for u in resolved_users if u.pk not in prior_user_ids]
        added_contacts = [
            c for c in resolved_contacts
            if c.get('slug') and c['slug'] not in prior_contact_slugs
        ]
        if not added_users and not added_contacts:
            return

        from .notify import dispatch_mentions
        try:
            dispatch_mentions(
                note=self.instance,
                added_users=added_users,
                added_contacts=added_contacts,
                source_obj=self.get_mention_source(),
                source_url=self.get_mention_source_url(),
                source_label=self.get_mention_source_label(),
                source_product=_current_product_code(),
                author=author,
            )
        except Exception:
            logger.exception(
                'MentionFormMixin: dispatch_mentions raised (note=%s)',
                getattr(self.instance, 'pk', '?'),
            )
