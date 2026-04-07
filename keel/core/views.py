"""Shared views for DockLabs products.

Usage in urls.py:
    from keel.core.views import health_check, robots_txt, LandingView

    urlpatterns = [
        path('health/', health_check, name='health_check'),
        path('robots.txt', robots_txt, name='robots_txt'),
        path('', LandingView.as_view(
            stats=[...],
            features=[...],
            steps=[...],
        ), name='landing'),
    ]
"""
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView


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


class LandingView(TemplateView):
    """Shared landing page view for all DockLabs products.

    Provides a consistent landing experience by extending Keel's
    `keel/layouts/landing.html`. Products configure content via class
    attributes or constructor params.

    Usage in urls.py:
        from keel.core.views import LandingView

        path('', LandingView.as_view(
            template_name='landing.html',  # product-specific template
            stats=[
                {'value': '12', 'label': 'Active Programs'},
                ...
            ],
            features=[
                {'icon': 'bi-bank2', 'title': 'Grants',
                 'description': '...', 'color': 'blue'},
                ...
            ],
            steps=[
                {'title': 'Register', 'description': '...'},
                ...
            ],
            authenticated_redirect='dashboard',  # url name to redirect logged-in users
        ), name='landing'),

    Or subclass for products that need dynamic data:

        class MyLandingView(LandingView):
            def get_landing_stats(self):
                return [
                    {'value': MyModel.objects.count(), 'label': 'Records'},
                    ...
                ]
    """
    template_name = 'landing.html'
    stats = None
    features = None
    steps = None
    authenticated_redirect = None  # url name (e.g. 'dashboard') or None to render same page

    def dispatch(self, request, *args, **kwargs):
        if self.authenticated_redirect and request.user.is_authenticated:
            return redirect(self.authenticated_redirect)
        return super().dispatch(request, *args, **kwargs)

    def get_landing_stats(self):
        return self.stats or []

    def get_landing_features(self):
        return self.features or []

    def get_landing_steps(self):
        return self.steps or []

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['landing_stats'] = self.get_landing_stats()
        ctx['landing_features'] = self.get_landing_features()
        ctx['landing_steps'] = self.get_landing_steps()
        return ctx
