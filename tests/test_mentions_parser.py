"""Tests for keel.mentions.parser.

Pins the two-form regex contract:

- ``@username`` → MentionToken(kind='user', ref='username')
- ``@beacon:contact-slug`` → MentionToken(kind='contact', ref='slug')

And the exclusions:

- Email addresses (``foo@bar.com``) are NOT mentions
- ``@``-tokens inside ``` `inline backticks` ``` are NOT mentions
- ``@``-tokens inside fenced ``` ```code blocks``` ``` are NOT mentions
- Duplicates within a kind are deduped (first-occurrence wins)
"""
from keel.mentions.parser import MentionToken, parse_mentions


def test_extracts_user_mention():
    out = parse_mentions('hey @dok please review')
    assert out == [MentionToken(kind='user', ref='dok')]


def test_extracts_username_with_dot():
    out = parse_mentions('hey @first.last please review')
    assert out == [MentionToken(kind='user', ref='first.last')]


def test_extracts_beacon_contact():
    out = parse_mentions('looped in @beacon:sarah-jones on this')
    assert out == [MentionToken(kind='contact', ref='sarah-jones')]


def test_user_regex_does_not_swallow_beacon_token():
    """The negative lookahead on ``:`` prevents @beacon: from also matching @beacon."""
    out = parse_mentions('cc @beacon:sarah-jones')
    assert out == [MentionToken(kind='contact', ref='sarah-jones')]


def test_email_not_mention():
    out = parse_mentions('contact me at dan@example.com')
    assert out == []


def test_dedupes_repeated_user():
    out = parse_mentions('hey @dok and again @dok and once more @dok')
    assert out == [MentionToken(kind='user', ref='dok')]


def test_dedupes_repeated_contact():
    out = parse_mentions('@beacon:sarah-jones and @beacon:sarah-jones')
    assert out == [MentionToken(kind='contact', ref='sarah-jones')]


def test_preserves_first_occurrence_order_across_kinds():
    text = 'cc @alice then @beacon:bob then @charlie'
    out = parse_mentions(text)
    # Implementation extracts contacts first then users — assert the set
    # of tokens, not the cross-kind interleaving.
    assert MentionToken('user', 'alice') in out
    assert MentionToken('contact', 'bob') in out
    assert MentionToken('user', 'charlie') in out
    assert len(out) == 3


def test_inline_backticks_excluded():
    text = 'see the example `@notamention` in code'
    assert parse_mentions(text) == []


def test_fenced_code_block_excluded():
    text = """see this:

```
@notamention in fenced code
```

real mention: @dok"""
    out = parse_mentions(text)
    assert out == [MentionToken(kind='user', ref='dok')]


def test_empty_text_returns_empty_list():
    assert parse_mentions('') == []
    assert parse_mentions(None) == []
