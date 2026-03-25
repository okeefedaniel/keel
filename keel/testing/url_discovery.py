"""Autodiscover all registered Django URL patterns at runtime.

Generates Python code that can be injected into the smoke test script
to test every parameterless URL in the product.

Usage (inside the generated smoke test script):
    The code from generate_discovery_code() introspects urlpatterns,
    filters to parameterless list/dashboard views, and GETs each one.
"""


def generate_discovery_code():
    """Return Python code that discovers and tests all parameterless URLs.

    This code runs inside the generated smoke test subprocess after
    django.setup() has been called.
    """
    return r'''
# ── URL Autodiscovery ──
section = 'URL Autodiscovery'
try:
    from django.urls import URLPattern, URLResolver, get_resolver
    import re

    def _collect_urls(resolver=None, prefix=''):
        """Recursively collect all parameterless URL patterns."""
        if resolver is None:
            resolver = get_resolver()
        urls = []
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                new_prefix = prefix + str(pattern.pattern)
                urls.extend(_collect_urls(pattern, new_prefix))
            elif isinstance(pattern, URLPattern):
                full_pattern = prefix + str(pattern.pattern)
                # Skip patterns with parameters (angle brackets)
                if '<' in full_pattern:
                    continue
                # Skip admin, static, __debug__ etc
                if any(skip in full_pattern for skip in ('admin/', '__debug__', 'static/', 'media/')):
                    continue
                # Convert regex-style pattern to URL path
                url = '/' + full_pattern.rstrip('$').lstrip('^')
                if not url.endswith('/') and '.' not in url.split('/')[-1]:
                    url += '/'
                urls.append(url)
        return urls

    discovered = _collect_urls()
    # Deduplicate and sort
    discovered = sorted(set(discovered))

    # Already-tested URLs from the explicit config
    already_tested = set()
    for urls_list in auth_urls.values():
        already_tested.update(urls_list)
    for url in public_urls:
        already_tested.add(url)

    # Only test newly discovered URLs
    new_urls = [u for u in discovered if u not in already_tested]

    ok(section, f'Discovered {len(discovered)} parameterless URLs',
       f'{len(new_urls)} new, {len(already_tested)} already covered')

    # Test each discovered URL as the first authenticated role
    if demo_roles:
        disc_client = Client()
        disc_client.login(username=demo_roles[0], password=DEMO_PASSWORD)
        tested = 0
        errors = 0
        for url in new_urls:
            try:
                resp = disc_client.get(url)
                if resp.status_code >= 500:
                    fail(section, f'500 on {url}', f'status={resp.status_code}')
                    errors += 1
                else:
                    tested += 1
            except Exception:
                errors += 1
        check(section, errors == 0,
              f'All discovered URLs healthy ({tested} tested)',
              f'{errors} errors' if errors else '')
except Exception as e:
    fail(section, 'URL autodiscovery failed', str(e)[:300])
'''
