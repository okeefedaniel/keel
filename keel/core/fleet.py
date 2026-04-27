"""Canonical DockLabs fleet product list.

Previously duplicated across nine product ``settings.py`` files. Any
product add/rename/URL change required a nine-file edit with high drift
risk (Helm feed endpoints, fleet switcher links, Keel SSO redirects).

Products should import ``FLEET`` and assign it:

    from keel.core.fleet import FLEET
    KEEL_FLEET_PRODUCTS = FLEET

``KEEL_FLEET_PRODUCTS`` remains the setting name the rest of the suite
reads; only the source of truth is centralised here.

Each entry carries ``icon`` (a Bootstrap Icons class) and ``tagline``
(short capability label) so the fleet grid on every landing page can
render a real, distinct tile per product. Audit F-010.

Each peer also carries ``feed_url`` — the helm-feed aggregation
endpoint Helm polls to assemble the cross-suite dashboard. Helm's own
entry has no ``feed_url`` (it is the consumer, not a peer); fleet
iterators that want only peers should filter on ``p.get('feed_url')``.
"""

FLEET = [
    {'name': 'Helm',      'label': 'Helm',      'code': 'helm',
     'icon': 'bi-compass',         'tagline': 'Executive Dashboard',
     'url': 'https://helm.docklabs.ai/dashboard/'},
    {'name': 'Harbor',    'label': 'Harbor',    'code': 'harbor',
     'icon': 'bi-bank2',           'tagline': 'State Grants',
     'url': 'https://harbor.docklabs.ai/dashboard/',
     'feed_url': 'https://harbor.docklabs.ai/api/v1/helm-feed/'},
    {'name': 'Beacon',    'label': 'Beacon',    'code': 'beacon',
     'icon': 'bi-broadcast',       'tagline': 'CRM',
     'url': 'https://beacon.docklabs.ai/dashboard/',
     'feed_url': 'https://beacon.docklabs.ai/api/v1/helm-feed/'},
    {'name': 'Lookout',   'label': 'Lookout',   'code': 'lookout',
     'icon': 'bi-binoculars',      'tagline': 'Legislative',
     'url': 'https://lookout.docklabs.ai/dashboard/',
     'feed_url': 'https://lookout.docklabs.ai/api/v1/helm-feed/'},
    {'name': 'Bounty',    'label': 'Bounty',    'code': 'bounty',
     'icon': 'bi-globe',           'tagline': 'Federal Funds',
     'url': 'https://bounty.docklabs.ai/dashboard/',
     'feed_url': 'https://bounty.docklabs.ai/api/v1/helm-feed/'},
    {'name': 'Admiralty', 'label': 'Admiralty', 'code': 'admiralty',
     'icon': 'bi-shield-check',    'tagline': 'FOIA',
     'url': 'https://admiralty.docklabs.ai/dashboard/',
     'feed_url': 'https://admiralty.docklabs.ai/api/v1/helm-feed/'},
    {'name': 'Purser',    'label': 'Purser',    'code': 'purser',
     'icon': 'bi-safe2',           'tagline': 'Finance',
     'url': 'https://purser.docklabs.ai/dashboard/',
     'feed_url': 'https://purser.docklabs.ai/api/v1/helm-feed/'},
    {'name': 'Manifest',  'label': 'Manifest',  'code': 'manifest',
     'icon': 'bi-pen',             'tagline': 'Signing',
     'url': 'https://manifest.docklabs.ai/dashboard/',
     'feed_url': 'https://manifest.docklabs.ai/api/v1/helm-feed/'},
    {'name': 'Yeoman',    'label': 'Yeoman',    'code': 'yeoman',
     'icon': 'bi-calendar-event',  'tagline': 'Scheduling',
     'url': 'https://yeoman.docklabs.ai/dashboard/',
     'feed_url': 'https://yeoman.docklabs.ai/api/v1/helm-feed/'},
]
