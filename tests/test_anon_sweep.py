"""Tests for keel.testing.anon_sweep."""
from types import ModuleType

from django.http import HttpResponse, HttpResponseForbidden
from django.test import TestCase
from django.urls import path

from keel.testing.anon_sweep import format_failures, sweep_anonymous


def _ok_view(request):
    return HttpResponse('ok')


def _crashing_view(request):
    # The shape of the real bug: reads an attribute AnonymousUser lacks.
    if request.user.role == 'nope':
        return HttpResponseForbidden()
    return HttpResponse('ok')


def _deliberate_503_view(request):
    return HttpResponse('not configured', status=503)


def _urlconf(name, *patterns):
    """Build a throwaway urlconf.

    ROOT_URLCONF accepts a module object rather than only a dotted string,
    which keeps these fixtures next to the tests using them. It has to be a
    real ModuleType: Django's resolver cache keys on the urlconf, so
    anything unhashable (SimpleNamespace, a bare class) blows up in
    lru_cache instead of resolving.
    """
    module = ModuleType(name)
    module.urlpatterns = list(patterns)
    return module


_OK_URLS = _urlconf('_ok_urls', path('ok/', _ok_view))
_CRASH_URLS = _urlconf('_crash_urls', path('crash/', _crashing_view))
_UNAVAILABLE_URLS = _urlconf('_unavailable_urls', path('unavailable/', _deliberate_503_view))


class SweepAnonymousTests(TestCase):

    def test_passing_url_produces_no_failures(self):
        with self.settings(ROOT_URLCONF=_OK_URLS):
            self.assertEqual(sweep_anonymous(urls=['/ok/']), [])

    def test_view_crashing_for_anonymous_user_is_reported(self):
        with self.settings(ROOT_URLCONF=_CRASH_URLS):
            failures = sweep_anonymous(urls=['/crash/'])
        self.assertEqual(len(failures), 1)
        url, detail = failures[0]
        self.assertEqual(url, '/crash/')
        self.assertIn('500', detail)
        # The originating exception should reach the report, not just "500".
        self.assertIn('AttributeError', detail)

    def test_deliberate_503_is_not_a_failure(self):
        """503 is app code reporting itself unconfigured, not a crash.

        The /api/v1/ feed + intake endpoints return 503 by design when
        their API key is unset, which is the documented standalone-deploy
        behaviour. Django never emits 503 on its own.
        """
        with self.settings(ROOT_URLCONF=_UNAVAILABLE_URLS):
            self.assertEqual(sweep_anonymous(urls=['/unavailable/']), [])

    def test_format_failures_is_empty_when_clean(self):
        self.assertEqual(format_failures([]), '')

    def test_format_failures_lists_each_url(self):
        msg = format_failures([('/a/', 'status=500'), ('/b/', 'raised ValueError: x')])
        self.assertIn('2 URL(s) failed', msg)
        self.assertIn('/a/', msg)
        self.assertIn('/b/', msg)
