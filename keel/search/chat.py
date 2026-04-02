"""AI-powered natural language search with streaming responses.

Subclass SearchChat per product, providing prompts and a SearchEngine.

Usage:
    class GrantChat(SearchChat):
        engine = GrantSearchEngine()
        extract_prompt = "Extract search keywords..."
        explain_prompt = "You are Bounty..."

    chat = GrantChat()
    for chunk in chat.handle_stream(user_message='climate grants'):
        send_sse(chunk)
"""
import json
import logging
import re

from django.conf import settings as django_settings

from keel.core.ai import get_client, parse_json_response

logger = logging.getLogger(__name__)

AI_MODEL = getattr(django_settings, 'KEEL_AI_MODEL', 'claude-sonnet-4-20250514')


class SearchChat:
    """AI search chat — subclass per product.

    Set these class attributes:
        engine — SearchEngine instance
        extract_prompt — Prompt to extract keywords from user question
        explain_prompt — Prompt template with {question}, {query}, {results}, {count}
        no_results_prompt — Prompt template with {question}, {query}
        greeting_prompt — Prompt template with {question}
    """

    engine = None
    extract_prompt = ''
    explain_prompt = ''
    no_results_prompt = ''
    greeting_prompt = ''
    max_results = 20

    def handle_stream(self, user_message, filters=None):
        """Yields JSON string chunks for SSE streaming.

        Chunk types:
            {"type": "status", "content": "Searching..."}
            {"type": "results", "content": [...]}
            {"type": "delta", "content": "text chunk"}
            {"type": "done"}
            {"type": "greeting", "content": "..."}
            {"type": "error", "content": "..."}
        """
        client = get_client()
        if not client:
            yield json.dumps({'type': 'error', 'content': 'AI features require an API key.'})
            return

        # Step 1: Extract search keywords via Claude
        search_query, extracted_filters = self._extract_keywords(client, user_message)

        if not search_query:
            # Greeting or non-search message
            greeting = self._generate_greeting(client, user_message)
            yield json.dumps({'type': 'greeting', 'content': greeting})
            return

        yield json.dumps({'type': 'status', 'content': f'Searching for "{search_query}"...'})

        # Merge extracted filters with explicit filters
        merged_filters = {**(filters or {}), **(extracted_filters or {})}
        # Remove None values
        merged_filters = {k: v for k, v in merged_filters.items() if v is not None}

        # Step 2: Run the search
        results = list(self.engine.search(
            search_query,
            filters=merged_filters if merged_filters else None,
            limit=self.max_results,
        ))

        # Send results to frontend
        results_data = [self.format_result_for_frontend(r) for r in results]
        yield json.dumps({'type': 'results', 'content': results_data})

        if not results:
            no_results = self._generate_no_results(client, user_message, search_query)
            yield json.dumps({'type': 'delta', 'content': no_results})
            yield json.dumps({'type': 'done'})
            return

        # Step 3: Stream Claude's explanation
        result_text = self.format_results_for_prompt(results)
        prompt = self.explain_prompt.format(
            question=user_message,
            query=search_query,
            results=result_text,
            count=len(results),
        )

        try:
            with client.messages.stream(
                model=AI_MODEL,
                max_tokens=2000,
                messages=[{'role': 'user', 'content': prompt}],
            ) as stream:
                for text in stream.text_stream:
                    yield json.dumps({'type': 'delta', 'content': text})
        except Exception:
            logger.exception('AI stream failed')
            yield json.dumps({'type': 'delta', 'content': f'Found {len(results)} results matching "{search_query}".'})

        yield json.dumps({'type': 'done'})

    # -----------------------------------------------------------------------
    # Override points
    # -----------------------------------------------------------------------

    def format_result_for_frontend(self, result):
        """Format a model instance for the frontend results panel.

        Override to include product-specific fields.
        """
        return {
            'id': result.pk,
            'title': str(result),
            'url': f'/{result.pk}/',
        }

    def format_results_for_prompt(self, results):
        """Format results as text for the Claude explain prompt.

        Override to include product-specific details.
        """
        lines = []
        for r in results:
            lines.append(f"  - {r}")
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    def _extract_keywords(self, client, user_message):
        """Use Claude to parse natural language → (query_str, filters_dict)."""
        if not self.extract_prompt:
            return self._naive_extract(user_message), {}

        try:
            resp = client.messages.create(
                model=AI_MODEL,
                max_tokens=150,
                messages=[{'role': 'user', 'content': self.extract_prompt + user_message}],
            )
            extracted = parse_json_response(resp.content[0].text)
            if extracted:
                query = extracted.pop('query', '')
                return query, extracted
        except Exception:
            logger.exception('Keyword extraction failed')

        return self._naive_extract(user_message), {}

    def _generate_greeting(self, client, user_message):
        """Generate a greeting response for non-search messages."""
        if not self.greeting_prompt:
            return "I can help you search. Try asking about a topic."
        try:
            resp = client.messages.create(
                model=AI_MODEL,
                max_tokens=500,
                messages=[{'role': 'user', 'content': self.greeting_prompt.format(question=user_message)}],
            )
            return resp.content[0].text
        except Exception:
            return "I can help you search. Try asking about a topic."

    def _generate_no_results(self, client, user_message, search_query):
        """Generate a helpful no-results message."""
        if not self.no_results_prompt:
            return f'No results found for "{search_query}". Try different keywords.'
        try:
            resp = client.messages.create(
                model=AI_MODEL,
                max_tokens=500,
                messages=[{'role': 'user', 'content': self.no_results_prompt.format(
                    question=user_message, query=search_query,
                )}],
            )
            return resp.content[0].text
        except Exception:
            return f'No results found for "{search_query}". Try different keywords.'

    @staticmethod
    def _naive_extract(text):
        """Fallback keyword extraction without AI."""
        stop = {
            'what', 'which', 'are', 'is', 'the', 'a', 'an', 'in', 'on', 'of',
            'to', 'for', 'and', 'or', 'that', 'this', 'do', 'does', 'how',
            'about', 'me', 'show', 'find', 'list', 'all', 'please', 'any',
            'there', 'can', 'you', 'their', 'what', 'where', 'when', 'grants',
            'grant', 'funding', 'federal', 'opportunities', 'available',
        }
        words = re.findall(r'\w+', text.lower())
        keywords = [w for w in words if w not in stop and len(w) > 2]
        return ' '.join(keywords[:5])
