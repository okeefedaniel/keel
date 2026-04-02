"""keel.search — Shared PostgreSQL full-text search engine for DockLabs products.

Provides:
    SearchEngine — Base class for ranked FTS with instant typeahead
    SearchChat — AI-powered natural language search with streaming
    instant_search_view — Reusable JSON endpoint for typeahead
    chat_stream_view — Reusable SSE endpoint for AI chat
"""
from .engine import SearchEngine  # noqa: F401
from .chat import SearchChat  # noqa: F401
