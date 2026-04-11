"""Shared context processors for DockLabs products.

Usage in settings.py:
    TEMPLATES = [{
        'OPTIONS': {
            'context_processors': [
                ...
                'keel.core.context_processors.site_context',
            ],
        },
    }]

    # Required setting:
    KEEL_PRODUCT_NAME = 'Beacon'  # or 'Harbor', 'Lookout', etc.
"""
import re

from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone


def _safe_reverse(url_name):
    """Return the URL for *url_name*, or ``None`` if it is not registered."""
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return None


def _microsoft_login_url(request):
    """Resolve the Microsoft SSO login URL.

    Tries the convenience ``microsoft_login`` named URL first (defined by
    most products), then falls back to the allauth provider API.
    """
    url = _safe_reverse('microsoft_login')
    if url:
        return url

    # Fallback: ask allauth's provider registry for the URL.
    try:
        from allauth.socialaccount.providers import registry
        provider = registry.by_id('microsoft', request)
        return provider.get_login_url(request, process='login')
    except Exception:
        return None


def _keel_oidc_login_url(request):
    """Resolve the Keel OIDC ("Sign in with DockLabs") login URL.

    Returns ``None`` unless the product has configured the Keel OIDC
    provider via ``KEEL_OIDC_CLIENT_ID`` / ``SOCIALACCOUNT_PROVIDERS``.
    Phase 2b: this is the canonical suite-mode entry point; the Microsoft
    button should be suppressed when this one is active.

    allauth's openid_connect provider mounts URLs at
    ``/accounts/oidc/<provider_id>/login/`` (the prefix is configurable
    via ``SOCIALACCOUNT_OPENID_CONNECT_URL_PREFIX``). We construct the
    URL via reverse() rather than the provider registry because the
    registry lookup is finicky for dynamically-configured OIDC apps.
    """
    if not getattr(settings, 'KEEL_OIDC_CLIENT_ID', ''):
        return None
    try:
        return reverse('openid_connect_login', kwargs={'provider_id': 'keel'})
    except NoReverseMatch:
        return None


def site_context(request):
    """Inject site-wide template variables into every template context.

    Provides:
        SITE_NAME — from KEEL_PRODUCT_NAME setting
        CURRENT_YEAR — for copyright footers
        DEMO_MODE — whether demo login is enabled
        unread_notification_count — for authenticated users (notification bell)

    Auth URLs (for the shared login card):
        register_url — allauth signup page
        reset_password_url — allauth password-reset page
        microsoft_login_url — Microsoft Entra ID SSO entry-point
    """
    demo_mode = getattr(settings, 'DEMO_MODE', False)
    product_name = getattr(settings, 'KEEL_PRODUCT_NAME', 'DockLabs')
    # In demo mode, append "Demo" to the product name so the top-left
    # sidebar brand reads "Harbor Demo", "Beacon Demo", etc. — a clear
    # visual cue that this is a demo instance, not production.
    site_name = f'{product_name} Demo' if demo_mode else product_name

    context = {
        'SITE_NAME': site_name,
        'PRODUCT_ICON': getattr(settings, 'KEEL_PRODUCT_ICON', 'bi-gear'),
        'PRODUCT_SUBTITLE': getattr(settings, 'KEEL_PRODUCT_SUBTITLE', ''),
        'CURRENT_YEAR': timezone.now().year,
        'DEMO_MODE': demo_mode,
    }

    # ── Auth URLs for the shared login card ──────────────────────────
    register_url = _safe_reverse('account_signup')
    if register_url:
        context['register_url'] = register_url

    reset_password_url = (
        _safe_reverse('account_reset_password')
        or _safe_reverse('password_reset')
    )
    if reset_password_url:
        context['reset_password_url'] = reset_password_url

    # Show both SSO entry points when configured. "Sign in with DockLabs"
    # is the suite SSO (product → Keel → wherever Keel routes you), and
    # "Sign in with Microsoft" remains the direct Microsoft Entra path
    # for users who prefer the standalone flow or whose browser already
    # has a Microsoft session.
    #
    # Demo instances deliberately hide both SSO buttons. Demo sites are
    # supposed to have only the one-click demo role users — letting a
    # real DockLabs identity sign in would create a parallel
    # "persistent" account that lingers after the OIDC flow and
    # clutters the demo DB. Hiding the buttons here is a belt-and-
    # suspenders measure alongside middleware checks.
    if not context['DEMO_MODE']:
        keel_url = _keel_oidc_login_url(request)
        if keel_url:
            context['keel_login_url'] = keel_url
        ms_url = _microsoft_login_url(request)
        if ms_url:
            context['microsoft_login_url'] = ms_url

    if hasattr(request, 'user') and request.user.is_authenticated:
        # Try to resolve the notification count via the configured model
        # first (most reliable), then fall back to related manager names.
        model_path = getattr(settings, 'KEEL_NOTIFICATION_MODEL', None)
        if model_path:
            try:
                from django.apps import apps
                NotifModel = apps.get_model(model_path)
                context['unread_notification_count'] = (
                    NotifModel.objects.filter(
                        recipient=request.user, is_read=False,
                    ).count()
                )
            except (LookupError, Exception):
                pass
        else:
            # Fallback: try common related manager names from
            # AbstractNotification's %(app_label)s_notifications pattern.
            for attr in ('notifications', 'core_notifications'):
                manager = getattr(request.user, attr, None)
                if manager is not None:
                    context['unread_notification_count'] = (
                        manager.filter(is_read=False).count()
                    )
                    break

    return context


_FLEET_URL_REWRITE_RE = re.compile(r'^(https?://)(?!demo-)([a-z0-9-]+\.docklabs\.ai)', re.IGNORECASE)


def fleet_context(request):
    """Inject fleet-switching template variables.

    Provides:
        FLEET_PRODUCTS — list of dicts with name, label, code, url keys
        CURRENT_PRODUCT — code of the current product (e.g., 'harbor')

    Demo-aware URL rewriting: products configure a single canonical
    ``KEEL_FLEET_PRODUCTS`` list pointing at the production hostnames
    (``https://harbor.docklabs.ai/dashboard/`` etc.). When a request
    arrives on a ``demo-*.docklabs.ai`` hostname, every fleet URL is
    rewritten on the fly to its ``demo-<product>.docklabs.ai``
    equivalent so clicks in the fleet switcher keep the user inside
    the demo ecosystem instead of jumping to production. This lets
    every product ship the same fleet list without branching on
    environment.

    Usage in settings.py:
        TEMPLATES = [{
            'OPTIONS': {
                'context_processors': [
                    ...
                    'keel.core.context_processors.fleet_context',
                ],
            },
        }]

        KEEL_PRODUCT_CODE = 'harbor'
        KEEL_FLEET_PRODUCTS = [
            {'name': 'Helm', 'label': 'Helm', 'code': 'helm', 'url': 'https://helm.docklabs.ai/dashboard/'},
            {'name': 'Beacon', 'label': 'Beacon', 'code': 'beacon', 'url': 'https://beacon.docklabs.ai/dashboard/'},
            ...
        ]
    """
    products = getattr(settings, 'KEEL_FLEET_PRODUCTS', [])

    # Rewrite fleet URLs when serving a demo hostname so users stay
    # within the demo ecosystem. Production hosts are left alone.
    if request is not None:
        host = request.get_host().split(':', 1)[0]
        if host.startswith('demo-'):
            products = [
                {**p, 'url': _FLEET_URL_REWRITE_RE.sub(r'\1demo-\2', p.get('url', ''))}
                for p in products
            ]

    return {
        'FLEET_PRODUCTS': products,
        'CURRENT_PRODUCT': getattr(settings, 'KEEL_PRODUCT_CODE', ''),
    }


def _resolve_namespace_url(namespace):
    """Try several naming conventions to find a clickable URL for a namespace.

    Products use different patterns:
      - Harbor: ``name='list'`` (bare)
      - Beacon: ``name='interaction_list'`` (prefixed with singular model name)

    We try: list, index, dashboard, {singular}_list, {namespace}_list.
    """
    # Derive singular form: "interactions" → "interaction", "companies" → "company"
    ns = namespace.lower()
    if ns.endswith('ies'):
        singular = ns[:-3] + 'y'
    elif ns.endswith('ses') or ns.endswith('xes'):
        singular = ns[:-2]
    elif ns.endswith('s') and not ns.endswith('ss'):
        singular = ns[:-1]
    else:
        singular = ns

    # Also try common model names that differ from namespace
    # e.g. pipeline → opportunity_list, cadences → reminder_list
    alt_models = {
        'pipeline': 'opportunity',
        'cadences': 'reminder',
    }
    alt = alt_models.get(ns, '')

    candidates = [
        'list', 'index', 'dashboard',
        f'{singular}_list',   # interaction_list, company_list
        f'{ns}_list',         # interactions_list (rare but possible)
    ]
    if alt:
        candidates.append(f'{alt}_list')  # opportunity_list, reminder_list
    for suffix in candidates:
        url = _safe_reverse(f'{namespace}:{suffix}')
        if url:
            return url
    return None


def _singularize(word):
    """Best-effort singular: 'interactions' → 'interaction'."""
    w = word.lower()
    if w.endswith('ies'):
        return w[:-3] + 'y'
    if w.endswith('ses') or w.endswith('xes'):
        return w[:-2]
    if w.endswith('s') and not w.endswith('ss'):
        return w[:-1]
    return w


# Label overrides: raw title-cased name → display label
_LABEL_MAP = {
    # Plurals
    'Program': 'Programs', 'Application': 'Applications',
    'Award': 'Awards', 'Report': 'Reports', 'Packet': 'Packets',
    'Flow': 'Flows', 'Closeout': 'Closeouts', 'Drawdown': 'Cash Requests',
    'Opportunity': 'Opportunities', 'Bill': 'Bills',
    'User': 'Users', 'Invitation': 'Invitations',
    'Notification': 'Notifications', 'Request': 'Requests',
    'Reporting': 'Reports', 'Financial': 'Financial',
    'Keel Notifications': 'Notifications',
    'Task': 'Tasks', 'Interaction': 'Interactions',
    'Company': 'Companies', 'Contact': 'Contacts',
    'Note': 'Notes', 'Reminder': 'Reminders',
    # Acronyms
    'Foia': 'FOIA',
    # Full url_name label overrides
    'Interaction Create': 'Log Interaction',
    'Interaction Edit': 'Edit Interaction',
    'Opportunity Transition': 'Change Stage',
}

# Action label overrides: 'create' → 'Create', etc.
_ACTION_LABELS = {
    'create': 'Create', 'edit': 'Edit', 'update': 'Edit',
    'delete': 'Delete', 'detail': '', 'list': '',
    'complete': 'Complete', 'status': 'Status',
}


def breadcrumb_context(request):
    """Auto-generate breadcrumbs from the current URL resolver match.

    Provides ``auto_breadcrumbs`` — a list of ``{'label', 'url'}`` dicts.
    The last item has ``url=None`` (current page, not a link).

    Handles nested sections automatically: if ``url_name`` has a prefix
    that differs from the namespace (e.g. ``task_create`` inside the
    ``interactions`` namespace), the prefix becomes an intermediate crumb
    linked to ``{namespace}:{prefix}_list``.

    Trail structure::

        Product  ›  Namespace  [›  Sub-section]  ›  Page
        Beacon   ›  Interactions  ›  Tasks  ›  Create
    """
    product_name = getattr(settings, 'KEEL_PRODUCT_NAME', 'DockLabs')
    crumbs = [{'label': product_name, 'url': '/'}]

    skip_namespaces = {'admin', 'core', 'portal', 'keel_notifications',
                       'keel_accounts', 'keel_requests', 'beacon_core'}

    match = getattr(request, 'resolver_match', None)
    if not match:
        return {'auto_breadcrumbs': crumbs}

    url_name = match.url_name or ''
    namespace = match.namespace or ''
    ns_singular = _singularize(namespace) if namespace else ''

    # ── Parse url_name into (prefix, action) ────────────────────
    # e.g. 'task_create' → ('task', 'create')
    #      'interaction_list' → ('interaction', 'list')
    #      'list' → ('', 'list')
    #      'dashboard' → ('', 'dashboard')
    parts = url_name.rsplit('_', 1) if '_' in url_name else ['', url_name]
    prefix = parts[0] if len(parts) == 2 else ''
    action = parts[-1]

    # Detect sub-section: prefix differs from namespace singular
    # e.g. prefix='task' inside namespace='interactions' (singular='interaction')
    is_subsection = (
        prefix
        and prefix != ns_singular
        and prefix != namespace.lower()
        and action not in ('', )
    )

    # ── Namespace crumb ─────────────────────────────────────────
    if namespace and namespace.lower() not in skip_namespaces:
        ns_label = namespace.replace('_', ' ').replace('-', ' ').title()
        ns_label = _LABEL_MAP.get(ns_label, ns_label)

        # Skip if namespace label matches product name
        if ns_label.lower() != product_name.lower():
            ns_url = _resolve_namespace_url(namespace)

            # For the namespace's own list page, this IS the current page
            if url_name in ('list', f'{ns_singular}_list'):
                crumbs.append({'label': ns_label, 'url': None})
                return {'auto_breadcrumbs': crumbs}

            crumbs.append({'label': ns_label, 'url': ns_url})

    # ── Sub-section crumb (e.g. "Tasks" inside interactions) ────
    if is_subsection:
        sub_label = prefix.replace('-', ' ').title()
        sub_label = _LABEL_MAP.get(sub_label, sub_label)

        # For the sub-section's own list page, this IS the current page
        if action == 'list':
            crumbs.append({'label': sub_label, 'url': None})
            return {'auto_breadcrumbs': crumbs}

        # Link to the sub-section list
        sub_url = _safe_reverse(f'{namespace}:{prefix}_list')
        crumbs.append({'label': sub_label, 'url': sub_url})

        # Final crumb = action label
        action_label = _ACTION_LABELS.get(action, action.replace('-', ' ').title())
        if action_label:
            crumbs.append({'label': action_label, 'url': None})

        return {'auto_breadcrumbs': crumbs}

    # ── Standard final crumb (non-subsection) ───────────────────
    # Build a readable label from the full url_name
    label = url_name.replace('-', ' ').replace('_', ' ').title()

    # Strip common suffixes
    for suffix in (' List', ' Index', ' Home'):
        if label.endswith(suffix) and len(label) > len(suffix):
            label = label[:-len(suffix)].strip()
            break

    if label == 'List':
        if namespace:
            label = namespace.replace('_', ' ').replace('-', ' ').title()
        else:
            label = ''

    label = _LABEL_MAP.get(label, label)

    if label and label.lower() not in ('home', 'dashboard', product_name.lower()):
        crumbs.append({'label': label, 'url': None})
    elif label.lower() == 'dashboard':
        crumbs.append({'label': 'Dashboard', 'url': None})

    return {'auto_breadcrumbs': crumbs}
