"""Autodiscover all registered Django URL patterns at runtime.

Generates Python code that can be injected into the smoke test script
to test every parameterless URL in the product.

Usage (inside the generated smoke test script):
    The code from generate_discovery_code() introspects urlpatterns,
    filters to parameterless list/dashboard views, and GETs each one
    both as an authenticated role and logged out.

The URL collection and the logged-out sweep live in keel.testing.anon_sweep
so products can run the same checks from their own test suites; keel is
installed in every product venv, so the generated script imports it.
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
    from keel.testing.anon_sweep import collect_parameterless_urls, sweep_anonymous

    discovered = collect_parameterless_urls()

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

    # Test each discovered URL as the first authenticated role.
    # Demo users have unusable passwords (keel >= 0.20.1); use force_login.
    if demo_roles:
        disc_client = Client()
        try:
            disc_user = User.objects.get(username=demo_roles[0])
            disc_client.force_login(disc_user)
        except User.DoesNotExist:
            disc_user = None
        tested = 0
        errors = 0
        for url in new_urls:
            try:
                resp = disc_client.get(url)
                # Flag 500 exactly, never >=500 — Django raises on an
                # unhandled exception and never emits 503, so a 503 is
                # always app code deliberately reporting itself
                # unconfigured (the documented standalone-deploy
                # behaviour of the /api/v1/ feed endpoints), not a crash.
                # Matches keel.testing.anon_sweep.
                if resp.status_code == 500:
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

# ── Anonymous URL Sweep ──
# The pass above force_logins first, so it is structurally blind to views
# that crash only for AnonymousUser (no .role / .organization). Beacon
# shipped two such 500s. Sweep the same URLs logged out.
section = 'Anonymous URL Sweep'
try:
    from keel.testing.anon_sweep import collect_parameterless_urls, sweep_anonymous

    swept = collect_parameterless_urls()
    anon_failures = sweep_anonymous(urls=swept)
    for anon_url, anon_detail in anon_failures:
        fail(section, f'500 on logged-out GET {anon_url}', anon_detail)
    check(section, not anon_failures,
          f'All URLs handle logged-out requests ({len(swept)} swept)',
          f'{len(anon_failures)} failing' if anon_failures else '')
except Exception as e:
    fail(section, 'Anonymous sweep failed', str(e)[:300])
'''
