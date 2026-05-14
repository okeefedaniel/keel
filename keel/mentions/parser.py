"""Parse @-mention tokens from free text and resolve to recipients.

Two token forms:

    @username                  → MentionToken(kind='user',    ref='username')
    @beacon:contact-slug       → MentionToken(kind='contact', ref='contact-slug')

The user regex carries a negative lookahead on ``:`` so ``@beacon:foo``
does not also match as ``@beacon``. Email addresses (``foo@bar.com``)
are excluded by the leading negative lookbehind on word-char/dot.

Tokens inside fenced code blocks (``` ``` ... ``` ```) and inline
backticks (``` `...` ```) are ignored — those are author markup, not
mention intent.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

# Public token shape (re-exported via keel.mentions package).
@dataclass(frozen=True)
class MentionToken:
    kind: str  # 'user' or 'contact'
    ref: str   # username for users; slug for contacts


# Regex
#
# The user regex's negative lookahead (?!:) blocks matching the ``beacon``
# in ``@beacon:slug`` ONLY when paired with stripping contact matches from
# the text before scanning for users — otherwise greedy backtracking would
# match ``@beaco`` (5 chars) after rejecting ``@beacon`` (6 chars). Order
# matters: extract contacts, strip the matched regions, then scan for users.
_USER_RE = re.compile(r'(?<![\w.])@([a-zA-Z0-9_.]+)')
_CONTACT_RE = re.compile(r'(?<![\w.])@beacon:([a-z0-9-]+)')
_FENCED_RE = re.compile(r'```.*?```', re.DOTALL)
_INLINE_RE = re.compile(r'`[^`]*`')


def _strip_code(text: str) -> str:
    """Remove fenced and inline code regions before token extraction."""
    text = _FENCED_RE.sub('', text)
    text = _INLINE_RE.sub('', text)
    return text


# Hard cap on input length so a pathological note can't DoS the regex
# engine. 100KB is ~25k words — far beyond any realistic comment. Past
# this, we silently truncate before parsing.
_MAX_INPUT_CHARS = 100_000


def parse_mentions(text: str) -> list[MentionToken]:
    """Extract @-mention tokens from a note's text content.

    Dedupes within each kind while preserving first-occurrence order.
    Does NOT enforce the recipient cap — callers (the form mixin) do
    that after resolution.
    """
    if not text:
        return []

    # DoS guard: cap input length before regex backtracking.
    if len(text) > _MAX_INPUT_CHARS:
        text = text[:_MAX_INPUT_CHARS]
        logger.info(
            'mentions.parser: truncated input from %d to %d chars',
            len(text), _MAX_INPUT_CHARS,
        )

    stripped = _strip_code(text)

    seen: set[tuple[str, str]] = set()
    out: list[MentionToken] = []

    # IMPORTANT: extract contacts FIRST, then strip those regions from the
    # text before scanning for user mentions. Otherwise the greedy user
    # regex would backtrack and match ``@beaco`` from ``@beacon:slug``.
    for match in _CONTACT_RE.finditer(stripped):
        slug = match.group(1)
        key = ('contact', slug)
        if key not in seen:
            seen.add(key)
            out.append(MentionToken(kind='contact', ref=slug))

    user_scan = _CONTACT_RE.sub('', stripped)
    for match in _USER_RE.finditer(user_scan):
        username = match.group(1)
        key = ('user', username)
        if key not in seen:
            seen.add(key)
            out.append(MentionToken(kind='user', ref=username))

    return out


def _current_product_code() -> str:
    return (getattr(settings, 'KEEL_PRODUCT_CODE', '') or '').lower()


def resolve_users(usernames: Iterable[str], requester) -> list:
    """Resolve a list of usernames to KeelUser objects, org-scoped.

    Rules:
    - Cross-org superuser (e.g. dokadmin with organization=None): match across orgs.
    - Non-superuser with organization=None: fails closed (returns []).
    - Otherwise: filter to requester.organization.
    - Require is_active=True.
    - Require an active ProductAccess row for the current product.
    - Exclude the requester themselves (no self-mention).
    - .distinct() to defeat fan-out via the ProductAccess join.
    """
    usernames = list({u for u in usernames if u})
    if not usernames:
        return []

    User = get_user_model()
    qs = User.objects.filter(username__in=usernames, is_active=True)

    requester_org = getattr(requester, 'organization', None)
    is_superuser = bool(getattr(requester, 'is_superuser', False))

    if is_superuser and requester_org is None:
        # dokadmin / cross-org superuser: no org filter.
        pass
    elif requester_org is None:
        logger.warning(
            'mentions.resolve_users: non-superuser %r has organization=None; '
            'returning empty match set', getattr(requester, 'username', '?'),
        )
        return []
    else:
        qs = qs.filter(organization=requester_org)

    product = _current_product_code()
    if product:
        qs = qs.filter(
            product_access__product=product,
            product_access__is_active=True,
        )

    if requester is not None and getattr(requester, 'pk', None):
        qs = qs.exclude(pk=requester.pk)

    return list(qs.distinct())


def resolve_contacts(slugs: Iterable[str], requester) -> list[dict]:
    """Resolve Beacon contact slugs to canonical metadata.

    Cross-product call to Beacon's lookup endpoint. Returns [] when:
    - Beacon not configured (BEACON_INTAKE_URL/_API_KEY missing)
    - Network/timeout/error
    - Beacon returned an empty list

    Each dict carries: slug, display_name, organization, url.
    """
    slugs = list({s for s in slugs if s})
    if not slugs:
        return []

    from .beacon import is_available, search_contacts_by_slugs
    if not is_available():
        return []

    try:
        return search_contacts_by_slugs(slugs, requester=requester)
    except Exception:
        logger.warning('mentions.resolve_contacts: cross.peer_unreachable', exc_info=True)
        return []
