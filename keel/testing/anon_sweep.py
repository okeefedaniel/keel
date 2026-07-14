"""Anonymous URL sweep — every registered URL must survive a logged-out request.

An authenticated sweep cannot catch views that read ``request.user``
attributes before deferring to ``LoginRequiredMixin``. Those views work
fine for every logged-in role and blow up only for ``AnonymousUser``,
which has no ``.role`` / ``.organization`` / product-specific attributes.

Beacon shipped exactly that on ``/auth/adoption/``::

    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in ADMIN_ROLES:   # AnonymousUser has no .role
            return HttpResponseForbidden(...)
        return super().dispatch(request, *args, **kwargs)

which returned a 500 to anyone whose session had expired. The
authenticated sweep in ``url_discovery`` never saw it, because it
force_logins first.

The contract here is deliberately narrow: a logged-out GET may redirect
(302), forbid (403), or 404 — it may not 5xx and it may not raise. What
the right logged-out response *is* stays a per-view decision; this only
asserts the view handles the case at all.

Products run it from their own test suite so it gates every PR::

    from keel.testing.anon_sweep import sweep_anonymous

    class AnonymousURLSweepTests(TestCase):
        def test_no_url_5xxs_when_logged_out(self):
            self.assertEqual(sweep_anonymous(), [])
"""
import sys

from django.core.signals import got_request_exception
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver

# Paths whose logged-out behaviour is Django's or a vendor's problem,
# not ours. `admin/` self-redirects to its own login; the static/media
# handlers aren't views at all.
DEFAULT_SKIP = ('admin/', '__debug__', 'static/', 'media/')


def collect_parameterless_urls(skip=DEFAULT_SKIP):
    """Return every registered URL path that takes no parameters.

    Patterns carrying converters or named groups are skipped — both
    contain '<', which is also why regex groups like (?P<pk>...) fall
    out here. Sweeping those would need fixture objects to build a
    real URL, which is the job of a product's own view tests.
    """
    def _walk(resolver=None, prefix=''):
        if resolver is None:
            resolver = get_resolver()
        found = []
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                found.extend(_walk(pattern, prefix + str(pattern.pattern)))
            elif isinstance(pattern, URLPattern):
                full = prefix + str(pattern.pattern)
                if '<' in full or any(s in full for s in skip):
                    continue
                url = '/' + full.rstrip('$').lstrip('^')
                if not url.endswith('/') and '.' not in url.split('/')[-1]:
                    url += '/'
                found.append(url)
        return found

    return sorted(set(_walk()))


def sweep_anonymous(urls=None, skip=DEFAULT_SKIP, client=None):
    """GET each URL logged out. Return [(url, detail)] for each failure.

    An empty list means every URL handled the logged-out request. The
    client is built with raise_request_exception=False so a view that
    raises is recorded as a failure and the sweep continues to the next
    URL rather than aborting on the first one.
    """
    client = client or Client(raise_request_exception=False)
    failures = []
    captured = {}

    def _capture(sender, **kwargs):
        captured['exc'] = sys.exc_info()[1]

    # The test client clears its own exc_info before returning, so the
    # signal is the only way to name the exception behind a 500. Worth the
    # wiring: "status=500" alone sends the reader to the logs, while
    # "AttributeError: 'AnonymousUser' object has no attribute 'role'"
    # is the whole diagnosis.
    got_request_exception.connect(_capture)
    try:
        for url in (collect_parameterless_urls(skip=skip) if urls is None else urls):
            captured.pop('exc', None)
            try:
                response = client.get(url)
            except Exception as exc:  # noqa: BLE001 — report, don't abort the sweep
                failures.append((url, f'raised {type(exc).__name__}: {exc}'))
                continue
            # 500 exactly, not >=500: Django emits 500 for an unhandled
            # exception and never emits 503, so a 503 here is always app
            # code deliberately reporting itself unconfigured — the
            # documented standalone-deploy behaviour of the /api/v1/ feed
            # and intake endpoints, not a crash.
            if response.status_code == 500:
                detail = 'status=500'
                exc = captured.get('exc')
                if exc is not None:
                    detail += f' ({type(exc).__name__}: {exc})'
                failures.append((url, detail))
    finally:
        got_request_exception.disconnect(_capture)

    return failures


def format_failures(failures):
    """Render sweep_anonymous() output as an assertion message."""
    if not failures:
        return ''
    lines = [f'{len(failures)} URL(s) failed an anonymous request:']
    lines += [f'  {url} — {detail}' for url, detail in failures]
    return '\n'.join(lines)
