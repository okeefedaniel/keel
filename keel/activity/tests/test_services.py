"""Tests for keel.activity.services — record_activity() and the _skip_promotion ContextVar.

Limited to non-DB unit tests for the keel-side test suite. Full integration tests for
record_activity() against a concrete Activity model live in the per-product test suites
(helm/tasks/tests/, manifest/signatures/tests/, beacon/interactions/tests/).
"""
import asyncio

from keel.activity.services import (
    _skip_promotion,
    is_promotion_skipped,
    skip_promotion_guard,
    build_deep_link,
)


def test_skip_promotion_default_is_false():
    """Outside the guard, the ContextVar reads False."""
    assert is_promotion_skipped() is False


def test_skip_promotion_guard_sets_and_resets():
    assert is_promotion_skipped() is False

    with skip_promotion_guard():
        assert is_promotion_skipped() is True

    assert is_promotion_skipped() is False


def test_skip_promotion_guard_resets_on_exception():
    try:
        with skip_promotion_guard():
            assert is_promotion_skipped() is True
            raise RuntimeError('boom')
    except RuntimeError:
        pass

    # Even after exception, the ContextVar is reset.
    assert is_promotion_skipped() is False


def test_skip_promotion_guard_nested():
    with skip_promotion_guard():
        assert is_promotion_skipped() is True
        with skip_promotion_guard():
            assert is_promotion_skipped() is True
        # Inner exit doesn't unset; outer is still True.
        assert is_promotion_skipped() is True
    assert is_promotion_skipped() is False


def test_skip_promotion_async_isolation():
    """ContextVar (not threading.local) means async tasks get their own context.

    A task running concurrently with the guard set in another task should NOT see the
    guard as True. This is what makes the guard async-safe.
    """
    async def with_guard():
        with skip_promotion_guard():
            assert is_promotion_skipped() is True
            await asyncio.sleep(0)  # yield to scheduler
            assert is_promotion_skipped() is True

    async def without_guard():
        # Without setting the guard in this task's context, it reads False even
        # though another task may have set it.
        await asyncio.sleep(0)
        assert is_promotion_skipped() is False

    async def main():
        await asyncio.gather(with_guard(), without_guard())

    asyncio.run(main())
    # Outside the gather, the ContextVar reads False (guard was never set in this context).
    assert is_promotion_skipped() is False


def test_build_deep_link_none_target_returns_empty():
    assert build_deep_link(None) == ''


def test_build_deep_link_target_without_get_absolute_url(settings):
    settings.KEEL_PRODUCT_BASE_URL = 'https://helm.docklabs.ai'

    class NoUrl:
        pass

    assert build_deep_link(NoUrl()) == ''


def test_build_deep_link_prefixes_base_url(settings):
    settings.KEEL_PRODUCT_BASE_URL = 'https://helm.docklabs.ai'

    class FakeProject:
        def get_absolute_url(self):
            return '/tasks/projects/abc/'

    assert build_deep_link(FakeProject()) == 'https://helm.docklabs.ai/tasks/projects/abc/'


def test_build_deep_link_strips_trailing_slash_on_base(settings):
    settings.KEEL_PRODUCT_BASE_URL = 'https://helm.docklabs.ai/'  # trailing slash

    class FakeProject:
        def get_absolute_url(self):
            return '/x/'

    assert build_deep_link(FakeProject()) == 'https://helm.docklabs.ai/x/'


def test_build_deep_link_no_base_url_falls_back_to_relative(settings):
    settings.KEEL_PRODUCT_BASE_URL = ''

    class FakeProject:
        def get_absolute_url(self):
            return '/foo/'

    # Returns the relative path. Helm aggregator will refuse to consume this, which is
    # the right failure mode (forces base URL configuration).
    assert build_deep_link(FakeProject()) == '/foo/'


def test_build_deep_link_swallows_get_absolute_url_exception(settings):
    settings.KEEL_PRODUCT_BASE_URL = 'https://helm.docklabs.ai'

    class Broken:
        def get_absolute_url(self):
            raise ValueError('NoReverseMatch or similar')

    # Exception is swallowed; empty string returned. Activity rows tolerate empty deep_link.
    assert build_deep_link(Broken()) == ''
