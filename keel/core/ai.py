"""Shared Claude AI client wrapper for DockLabs products.

Provides thin helpers around the Anthropic SDK so products don't duplicate
client initialization, JSON response parsing, and error handling.

Products keep their own prompts and domain logic — this module handles
the plumbing.

Usage:
    from keel.core.ai import get_client, call_claude, parse_json_response

    # Simple call
    client = get_client()
    response = call_claude(
        client,
        system='You are a helpful assistant.',
        user_message='Summarize this document.',
    )

    # JSON-returning call
    data = parse_json_response(response)
    # data is a dict, or None on parse failure

Configuration:
    ANTHROPIC_API_KEY — required (in settings or env)
    KEEL_AI_MODEL — optional, defaults to 'claude-sonnet-4-20250514'
    KEEL_AI_MAX_TOKENS — optional, defaults to 500
"""
import json
import logging
import os
import re

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'claude-sonnet-4-20250514'
DEFAULT_MAX_TOKENS = 500


def get_client(api_key=None):
    """Return an Anthropic client instance.

    Resolves API key from (in order):
    1. Explicit ``api_key`` parameter
    2. ``settings.ANTHROPIC_API_KEY``
    3. ``ANTHROPIC_API_KEY`` environment variable

    Returns None if anthropic is not installed or no key is found.
    """
    try:
        import anthropic
    except ImportError:
        logger.error('anthropic package not installed — pip install anthropic')
        return None

    key = (
        api_key
        or getattr(settings, 'ANTHROPIC_API_KEY', None)
        or os.environ.get('ANTHROPIC_API_KEY')
    )
    if not key:
        logger.error('No Anthropic API key found')
        return None

    return anthropic.Anthropic(api_key=key)


def call_claude(client, system, user_message, model=None, max_tokens=None):
    """Make a standard Claude API call and return the text response.

    Args:
        client: Anthropic client from ``get_client()``.
        system: System prompt string.
        user_message: User message string.
        model: Model ID (defaults to KEEL_AI_MODEL setting or claude-sonnet-4-20250514).
        max_tokens: Max tokens (defaults to KEEL_AI_MAX_TOKENS setting or 500).

    Returns:
        Response text string, or None on error.
    """
    if client is None:
        return None

    model = model or getattr(settings, 'KEEL_AI_MODEL', DEFAULT_MODEL)
    max_tokens = max_tokens or getattr(settings, 'KEEL_AI_MAX_TOKENS', DEFAULT_MAX_TOKENS)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{'role': 'user', 'content': user_message}],
        )
        return response.content[0].text
    except Exception:
        logger.exception('Claude API call failed')
        return None


def parse_json_response(text):
    """Parse a JSON response from Claude, stripping markdown fences if present.

    Handles common patterns:
    - Raw JSON
    - ```json ... ``` fenced blocks
    - ``` ... ``` fenced blocks

    Returns:
        Parsed dict/list, or None on failure.
    """
    if not text:
        return None

    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning('Failed to parse JSON from Claude response: %s', text[:200])
        return None
