"""Reusable search views for DockLabs products.

Products call these from their own URL patterns, passing their
SearchEngine and SearchChat instances.
"""
import json

from django.http import JsonResponse, StreamingHttpResponse


def instant_search_view(request, engine):
    """JSON endpoint for typeahead search.

    GET ?q=search+terms&agency=NSF&status=posted

    Returns: {"results": [...], "query": "..."}
    """
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': [], 'query': query})

    # Collect filter params (exclude q and standard Django params)
    filters = {
        k: v for k, v in request.GET.items()
        if k not in ('q', 'page', 'view', 'format')
    }

    results = engine.instant_search(query, filters=filters or None)
    return JsonResponse({'results': results, 'query': query})


def chat_stream_view(request, chat):
    """SSE streaming endpoint for AI chat search.

    POST with JSON body: {"message": "..."}
    Returns: text/event-stream with JSON chunks.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = json.loads(request.body)
        user_message = body.get('message', '').strip()
    except (json.JSONDecodeError, AttributeError):
        user_message = request.POST.get('message', '').strip()

    if not user_message:
        return JsonResponse({'error': 'No message provided'}, status=400)

    def stream():
        for chunk in chat.handle_stream(user_message):
            yield f"data: {chunk}\n\n"

    response = StreamingHttpResponse(stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
