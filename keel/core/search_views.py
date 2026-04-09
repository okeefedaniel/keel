"""Shared search view for DockLabs products.

Provides a ready-to-use ``/search/`` endpoint that the ⌘K modal submits
to. Products register searchable models via the ``KEEL_SEARCH_MODELS``
setting, and the view does ``Q(field__icontains=q)`` across all of them.

Usage in product settings.py::

    KEEL_SEARCH_MODELS = [
        {
            'model': 'grants.Program',
            'fields': ['name', 'description'],
            'label': 'Programs',
            'icon': 'bi-collection',
            'url_pattern': '/grants/programs/{pk}/',
            'title_field': 'name',
            'subtitle_field': 'description',
        },
        ...
    ]

Usage in product urls.py::

    from keel.core.search_views import search_view
    path('search/', search_view, name='search'),
"""
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

logger = logging.getLogger(__name__)

# Max results per section
SECTION_LIMIT = 20


@login_required
def search_view(request):
    """Shared search page for the ⌘K modal.

    Reads ``KEEL_SEARCH_MODELS`` from settings. Each entry defines a
    model, the fields to search, and how to display the results.
    Falls back to searching users if no models are configured.
    """
    query = request.GET.get('q', '').strip()
    sections = []
    total_count = 0

    if query and len(query) >= 2:
        search_models = getattr(settings, 'KEEL_SEARCH_MODELS', [])

        # If no models configured, search users as a baseline
        if not search_models:
            search_models = [
                {
                    'model': settings.AUTH_USER_MODEL,
                    'fields': ['username', 'email', 'first_name', 'last_name'],
                    'label': 'Users',
                    'icon': 'bi-people',
                    'title_field': 'get_full_name',
                    'subtitle_field': 'email',
                },
            ]

        for spec in search_models:
            try:
                model = apps.get_model(spec['model'])
            except (LookupError, ValueError):
                logger.warning('Search model %s not found', spec['model'])
                continue

            # Build Q filter across all specified fields
            q_filter = Q()
            for field in spec.get('fields', []):
                q_filter |= Q(**{f'{field}__icontains': query})

            qs = model.objects.filter(q_filter)[:SECTION_LIMIT]
            results = []
            for obj in qs:
                title_field = spec.get('title_field', 'name')
                subtitle_field = spec.get('subtitle_field', '')

                # Support method calls (e.g. get_full_name)
                if callable(getattr(obj, title_field, None)):
                    title = getattr(obj, title_field)()
                else:
                    title = getattr(obj, title_field, str(obj))

                subtitle = ''
                if subtitle_field:
                    if callable(getattr(obj, subtitle_field, None)):
                        subtitle = getattr(obj, subtitle_field)()
                    else:
                        subtitle = getattr(obj, subtitle_field, '')
                    # Truncate long subtitles
                    if len(str(subtitle)) > 120:
                        subtitle = str(subtitle)[:120] + '…'

                # Build URL from pattern or get_absolute_url
                url = ''
                url_pattern = spec.get('url_pattern', '')
                if url_pattern:
                    url = url_pattern.replace('{pk}', str(obj.pk))
                elif hasattr(obj, 'get_absolute_url'):
                    url = obj.get_absolute_url()

                # Optional badge (e.g. status field)
                badge = ''
                badge_color = 'secondary'
                badge_field = spec.get('badge_field', '')
                if badge_field:
                    raw = getattr(obj, badge_field, '')
                    if callable(raw):
                        raw = raw()
                    badge = str(raw).replace('_', ' ').title() if raw else ''
                    badge_color = spec.get('badge_color', 'secondary')

                results.append({
                    'title': title or str(obj),
                    'subtitle': subtitle,
                    'url': url,
                    'badge': badge,
                    'badge_color': badge_color,
                })

            if results:
                sections.append({
                    'label': spec.get('label', model._meta.verbose_name_plural.title()),
                    'icon': spec.get('icon', 'bi-search'),
                    'results': results,
                })
                total_count += len(results)

    return render(request, 'keel/search.html', {
        'query': query,
        'sections': sections,
        'total_count': total_count,
    })
