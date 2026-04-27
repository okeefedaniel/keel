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
from urllib.parse import urlencode, urlparse

from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.auth.views import LogoutView
from django.utils import timezone
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import RedirectView, TemplateView


@require_GET
@cache_control(max_age=86400)
def favicon_view(request):
    """Redirect `/favicon.ico` to the hashed static favicon.

    Products drop a `favicon.svg` (and optional `favicon.ico`) into
    `static/img/`; WhiteNoise serves them with content hashes in the URL,
    so browsers that request `/favicon.ico` directly 404 without this
    shim. Prefers SVG where available, falls back to ICO.
    """
    for candidate in ('img/favicon.svg', 'img/favicon.ico'):
        try:
            url = staticfiles_storage.url(candidate)
        except ValueError:
            continue
        return HttpResponseRedirect(url)
    return HttpResponse(status=404)


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


# ---------------------------------------------------------------------------
# Suite-wide logout
# ---------------------------------------------------------------------------

def _is_allowed_docklabs_redirect(url: str) -> bool:
    """Whitelist for post-logout redirect URIs.

    Only ``*.docklabs.ai`` hostnames (http/https) are permitted so the
    suite logout endpoint can't be abused as an open redirect.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    host = (parsed.netloc or '').lower().split(':', 1)[0]
    return host == 'docklabs.ai' or host.endswith('.docklabs.ai')


@require_http_methods(['GET', 'POST'])
def suite_logout_endpoint(request):
    """Keel-side endpoint for suite-wide logout.

    Products chain their own logout through here so that signing out of
    one product also clears the Keel IdP session. Without this the
    "Sign in with DockLabs" button silently re-authenticates the user
    from the still-active Keel cookie immediately after they logged out.

    Accepts ``?next=<product_home>`` and redirects back there after
    clearing the IdP session. ``next`` is validated against
    ``_is_allowed_docklabs_redirect`` to prevent open-redirect abuse.

    Wire in Keel's ``keel_site/urls.py``::

        from keel.core.views import suite_logout_endpoint
        path('suite/logout/', suite_logout_endpoint, name='suite_logout'),
    """
    if request.user.is_authenticated:
        # Stamp the suite-wide logout epoch so peer products can detect
        # this on their next request and tear down their stale local
        # session. .update() avoids signal noise and is atomic.
        User = get_user_model()
        User.objects.filter(pk=request.user.pk).update(
            last_logout_at=timezone.now(),
        )
    auth_logout(request)
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if not _is_allowed_docklabs_redirect(next_url):
        next_url = '/'
    return HttpResponseRedirect(next_url)


class SuiteLogoutView(LogoutView):
    """Per-product logout view that also tears down the Keel IdP session.

    Drop-in replacement for ``django.contrib.auth.views.LogoutView``.
    Django's LogoutView clears the product's local session as usual, and
    then ``get_success_url()`` chains the redirect through Keel's
    ``/suite/logout/?next=<product_home>`` endpoint so the IdP session
    is also cleared. After Keel logs the user out it redirects back to
    the product's home page.

    Demo instances chain through ``demo-keel.docklabs.ai`` automatically
    based on the ``Host`` header, so the same view works for both
    ecosystems without per-environment configuration.

    Accepts GET as well as POST — Django 5's LogoutView requires POST by
    default (to prevent CSRF-triggered logouts from ``<img>`` tags), but
    the DockLabs suite needs users to be able to break out of a stale
    session with a plain link click. Sign-out is not a destructive
    action, so relaxing this is fine.

    Usage in a product's urls.py::

        from keel.core.views import SuiteLogoutView

        urlpatterns = [
            path('auth/logout/', SuiteLogoutView.as_view(), name='logout'),
            ...
        ]
    """

    http_method_names = ['get', 'post', 'options']

    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)

    def get_success_url(self):
        # Django 5's LogoutView dispatches redirects through
        # get_success_url() (via RedirectURLMixin), not the old
        # get_next_page() hook. Always chain through Keel's
        # /suite/logout/ so the IdP session is torn down too — any
        # same-host ?next= is intentionally ignored so products can't
        # short-circuit the suite-wide logout chain. auth_logout() has
        # already run by the time this is called.
        host = self.request.get_host().split(':', 1)[0]
        keel_host = 'demo-keel.docklabs.ai' if host.startswith('demo-') else 'keel.docklabs.ai'
        product_home = self.request.build_absolute_uri('/')
        params = urlencode({'next': product_home})
        return f'https://{keel_host}/suite/logout/?{params}'
