"""Shared views for DockLabs products.

Usage in urls.py:
    from keel.core.views import health_check, robots_txt

    urlpatterns = [
        path('health/', health_check, name='health_check'),
        path('robots.txt', robots_txt, name='robots_txt'),
        ...
    ]
"""
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


@require_GET
def health_check(request):
    """Minimal health check for Railway / container orchestration."""
    return JsonResponse({'status': 'ok'})


@require_GET
@cache_control(max_age=86400)
def robots_txt(request):
    """Shared robots.txt disallowing admin, API, and auth paths."""
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /api/',
        'Disallow: /auth/',
        'Disallow: /accounts/',
        'Allow: /',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')
