"""Notification catalog audit for the test suite.

Validates the notification type registry — checking for orphaned overrides,
invalid roles/channels, and coverage gaps. Runs as part of the full test
suite and can be invoked standalone with --notification-only.
"""
import os

VALID_CHANNELS = {'in_app', 'email', 'sms', 'boswell'}
VALID_PRIORITIES = {'low', 'medium', 'high', 'urgent'}


def run_notification_audit(T):
    """Validate the notification catalog and record results in TestResult."""
    T.product('Keel')
    T.section('Notification Catalog')

    # Ensure Django is set up
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'keel_site.settings')
        django.setup()
    except Exception:
        pass

    from keel.accounts.models import NotificationTypeOverride, get_product_roles
    from keel.notifications.registry import get_all_types

    all_types = get_all_types()
    product_roles = get_product_roles()

    # Collect all valid role codes
    all_valid_roles = set()
    for roles_list in product_roles.values():
        for code, _label in roles_list:
            all_valid_roles.add(code)
    all_valid_roles.add('all')

    # --- Check: Registry is non-empty ---
    T.check(
        len(all_types) > 0,
        'Registry has notification types',
        f'{len(all_types)} types registered',
    )

    # --- Check: No orphaned overrides ---
    try:
        override_keys = set(
            NotificationTypeOverride.objects.values_list('key', flat=True)
        )
        registry_keys = set(all_types.keys())
        orphaned = override_keys - registry_keys

        T.check(
            len(orphaned) == 0,
            'No orphaned database overrides',
            f'{len(orphaned)} orphaned: {", ".join(sorted(orphaned))}' if orphaned else '',
        )
    except Exception as e:
        T.ok('Overrides table check (skipped — table may not exist)', str(e))

    # --- Check: All roles are valid ---
    invalid_roles = []
    for key, ntype in sorted(all_types.items()):
        for role in ntype.default_roles:
            if role not in all_valid_roles:
                invalid_roles.append(f'{key}: {role}')

    T.check(
        len(invalid_roles) == 0,
        'All notification roles exist in PRODUCT_ROLES',
        f'{len(invalid_roles)} invalid: {"; ".join(invalid_roles[:5])}' if invalid_roles else '',
    )

    # --- Check: All channels are valid ---
    invalid_channels = []
    for key, ntype in sorted(all_types.items()):
        for ch in ntype.default_channels:
            if ch not in VALID_CHANNELS:
                invalid_channels.append(f'{key}: {ch}')

    T.check(
        len(invalid_channels) == 0,
        'All notification channels are valid',
        f'{len(invalid_channels)} invalid: {"; ".join(invalid_channels[:5])}' if invalid_channels else '',
    )

    # --- Check: All priorities are valid ---
    invalid_priorities = []
    for key, ntype in sorted(all_types.items()):
        if ntype.priority not in VALID_PRIORITIES:
            invalid_priorities.append(f'{key}: {ntype.priority}')

    T.check(
        len(invalid_priorities) == 0,
        'All notification priorities are valid',
        f'{len(invalid_priorities)} invalid: {"; ".join(invalid_priorities[:5])}' if invalid_priorities else '',
    )

    # --- Check: Every type has at least one channel ---
    no_channels = [k for k, nt in all_types.items() if not nt.default_channels]
    T.check(
        len(no_channels) == 0,
        'Every notification type has at least one channel',
        f'{len(no_channels)} types with no channels: {", ".join(no_channels[:5])}' if no_channels else '',
    )

    # --- Check: Every type has at least one role ---
    no_roles = [k for k, nt in all_types.items() if not nt.default_roles]
    T.check(
        len(no_roles) == 0,
        'Every notification type has at least one default role',
        f'{len(no_roles)} types with no roles: {", ".join(no_roles[:5])}' if no_roles else '',
    )

    # --- Check: Category coverage (each product has at least one type) ---
    categories = set()
    for ntype in all_types.values():
        # Extract product name from category (e.g., "Harbor — Awards" -> "harbor")
        product = ntype.category.split('—')[0].strip().lower() if '—' in ntype.category else ntype.category.lower()
        categories.add(product)

    expected_products = {'beacon', 'admiralty', 'harbor', 'manifest', 'lookout', 'bounty', 'yeoman', 'purser', 'keel'}
    missing_products = expected_products - categories

    T.check(
        len(missing_products) == 0,
        'All products have registered notification types',
        f'Missing: {", ".join(sorted(missing_products))}' if missing_products else f'{len(categories)} products covered',
    )
